"use client";

import { CalendarCheck, Clock } from "lucide-react";
import { useCallStore } from "@/stores/callStore";

export function AppointmentPanel() {
  const offeredSlots = useCallStore((s) => s.offeredSlots);
  const offeredDepartment = useCallStore((s) => s.offeredDepartment);
  const booking = useCallStore((s) => s.booking);

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-medium">Appointment</h3>

      {booking ? (
        <div className="flex flex-col gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3">
          <div className="flex items-center gap-2 text-emerald-400">
            <CalendarCheck className="h-4 w-4" />
            <span className="text-sm font-medium">Booked</span>
          </div>
          <div className="text-sm">
            <p className="font-medium">{booking.doctor}</p>
            <p className="text-muted-foreground">
              {booking.department} &middot; {booking.when}
            </p>
            {booking.reason && (
              <p className="mt-1 text-xs text-muted-foreground">
                Reason: {booking.reason}
              </p>
            )}
          </div>
        </div>
      ) : offeredSlots.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground">
            Offered slots in {offeredDepartment}
          </p>
          {offeredSlots.map((slot) => (
            <div
              key={slot.slot_id}
              className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm"
            >
              <Clock className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="flex-1">{slot.when}</span>
              <span className="text-xs text-muted-foreground">{slot.doctor}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
          No availability checked yet.
        </p>
      )}
    </div>
  );
}
