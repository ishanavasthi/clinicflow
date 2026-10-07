"""Real SQLite transaction checks, including two simultaneous callers."""
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from clock import clinic_now
from db import get_session
from models import Appointment, Department, Doctor, Patient, Slot
from routes.appointments import router


class BookingTransactions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f'sqlite:///{self.tmp.name}/test.db', connect_args={'check_same_thread': False})
        SQLModel.metadata.create_all(self.engine)
        self.now = datetime(2030, 1, 7, 8, 0)
        with Session(self.engine) as s:
            s.add(Department(id=1, name='Orthopedics', floor='2'))
            s.add(Doctor(id=1, name='Synthetic Doctor', department_id=1))
            s.add(Patient(id=1, name='Synthetic One'))
            s.add(Patient(id=2, name='Synthetic Two'))
            for n, delta in enumerate([-1, 1, 5], 1):
                s.add(Slot(id=n, doctor_id=1, start=self.now + timedelta(hours=delta)))
            s.commit()
        self.app = FastAPI()
        self.app.include_router(router)
        def session():
            with Session(self.engine) as s:
                yield s
        self.app.dependency_overrides[get_session] = session
        self.app.dependency_overrides[clinic_now] = lambda: self.now
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def payload(self, patient=1, slot=2, request='request-one'):
        return {'patient_id': patient, 'slot_id': slot, 'reason': 'knee pain', 'request_id': request}

    def test_idempotent_retry_and_scoped_receipt(self):
        first = self.client.post('/appointments', json=self.payload())
        second = self.client.post('/appointments', json=self.payload())
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.json(), first.json())
        receipt = self.client.get('/appointments/requests/request-one?patient_id=1')
        self.assertEqual(receipt.json(), first.json())
        self.assertEqual(self.client.get('/appointments/requests/request-one?patient_id=2').status_code, 404)
        with Session(self.engine) as s:
            self.assertEqual(len(s.exec(select(Appointment)).all()), 1)

    def test_key_reuse_with_changed_booking_is_conflict(self):
        self.client.post('/appointments', json=self.payload())
        self.assertEqual(self.client.post('/appointments', json=self.payload(slot=3)).status_code, 409)
        with Session(self.engine) as s:
            self.assertFalse(s.get(Slot, 3).booked)

    def test_two_callers_cannot_claim_same_slot(self):
        def book(patient):
            with TestClient(self.app) as client:
                return client.post('/appointments', json=self.payload(patient=patient, request=f'request-{patient}')).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(book, [1, 2]))
        self.assertEqual(sorted(statuses), [200, 409])
        with Session(self.engine) as s:
            self.assertEqual(len(s.exec(select(Appointment)).all()), 1)

    def test_concurrent_same_request_returns_same_appointment(self):
        def book(_):
            with TestClient(self.app) as client:
                return client.post('/appointments', json=self.payload())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(book, [1, 2]))
        self.assertEqual([r.status_code for r in results], [200, 200])
        self.assertEqual(results[0].json()['appointment_id'], results[1].json()['appointment_id'])

    def test_past_and_time_preferences(self):
        response = self.client.get('/appointments/availability', params={'department': 'Orthopedics', 'not_before': '12:00'})
        self.assertEqual([s['slot_id'] for s in response.json()], [3])
        self.assertEqual(self.client.post('/appointments', json=self.payload(slot=1)).status_code, 422)
        self.assertEqual(self.client.get('/appointments/availability', params={'department':'Orthopedics', 'date':'bad'}).status_code, 422)
        self.assertEqual(self.client.get('/appointments/availability', params={'department':'Orthopedics', 'not_before':'27:00'}).status_code, 422)

if __name__ == '__main__':
    unittest.main()
