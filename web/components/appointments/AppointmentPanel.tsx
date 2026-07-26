"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  CalendarCheck,
  Clock,
  ShieldAlert,
  Stethoscope,
  UserRound,
} from "lucide-react";
import { popIn } from "@/lib/motion";
import { useCallStore } from "@/stores/callStore";

export function AppointmentPanel() {
  const offeredSlots = useCallStore((s) => s.offeredSlots);
  const offeredDepartment = useCallStore((s) => s.offeredDepartment);
  const booking = useCallStore((s) => s.booking);
  const routing = useCallStore((s) => s.routing);
  const isEmergency = !booking && (routing?.emergency ?? false);

  return (
    <div className="flex flex-col gap-3">
      <AnimatePresence mode="wait">
        {isEmergency ? (
          <motion.div
            key="emergency"
            variants={popIn}
            initial="hidden"
            animate="show"
            className="flex flex-col gap-2.5 rounded-lg border border-emergency/30 bg-emergency/10 p-3"
          >
            <div className="flex items-center gap-2 text-emergency">
              <ShieldAlert className="h-4 w-4" />
              <span className="text-sm font-medium">Emergency escalation</span>
            </div>
            <p className="text-sm">
              Intake skipped. Caller routed straight to the Emergency ward.
            </p>
            {routing?.reason && (
              <p className="text-xs text-muted-foreground">
                Trigger: {routing.reason}
              </p>
            )}
            <div className="flex items-center gap-2 rounded-md border border-emergency/20 bg-card px-3 py-2">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emergency opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emergency" />
              </span>
              <UserRound className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-medium">
                Connecting a clinician to take over the call
              </span>
            </div>
          </motion.div>
        ) : booking ? (
          <motion.div
            key="booked"
            variants={popIn}
            initial="hidden"
            animate="show"
            className="flex flex-col gap-2 rounded-lg border border-success/30 bg-success/10 p-3"
          >
            <div className="flex items-center gap-2 text-success">
              <CalendarCheck className="h-4 w-4" />
              <span className="text-sm font-medium">Appointment booked</span>
            </div>
            <div className="text-sm">
              <p className="flex items-center gap-1.5 font-medium">
                <Stethoscope className="h-3.5 w-3.5 text-muted-foreground" />
                {booking.doctor}
              </p>
              <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                {booking.department} &middot; {booking.when}
              </p>
              {booking.reason && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Reason: {booking.reason}
                </p>
              )}
            </div>
          </motion.div>
        ) : offeredSlots.length > 0 ? (
          <motion.div
            key="slots"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex flex-col gap-2"
          >
            <p className="font-mono text-[11px] text-muted-foreground">
              Offered in {offeredDepartment}
            </p>
            {offeredSlots.map((slot, i) => (
              <motion.div
                key={slot.slot_id}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.06 }}
                className="flex items-center gap-2 rounded-lg border border-border bg-elevated px-3 py-2 text-sm"
              >
                <Clock className="h-3.5 w-3.5 text-primary" />
                <span className="flex-1">{slot.when}</span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {slot.doctor}
                </span>
              </motion.div>
            ))}
          </motion.div>
        ) : (
          <p
            key="empty"
            className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground"
          >
            No availability checked yet.
          </p>
        )}
      </AnimatePresence>
    </div>
  );
}
