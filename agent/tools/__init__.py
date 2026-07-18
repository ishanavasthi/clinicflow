"""LiveKit function tools for the receptionist agent.

Implemented in M2:
    intake.py        update_intake(field, value)
    appointments.py  check_availability(dept, date), book_appointment(...)
    faq.py           answer_faq(topic)
    routing.py       route_to_department(dept, reason)

Every tool returns {ok, data|error} and never fabricates a result on failure.
"""
