import { TriangleAlert } from "lucide-react";
import type { DoctorSummary } from "@/lib/types";

/** Display name for a call's language code. */
export function languageLabel(code: string | undefined | null): string | null {
  if (code === "hi") return "Hindi";
  if (code === "en") return "English";
  return null;
}

/**
 * The English note for the doctor from a Hindi-enabled call. Complaint,
 * duration and key answers are model-written; the red flag and booking come
 * from the clinic system, and the patient's words are their exact phrase.
 */
export function DoctorSummaryCard({ summary }: { summary: DoctorSummary }) {
  const { structured } = summary;
  return (
    <div className="flex flex-col gap-3 text-sm">
      {structured.red_flag && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-destructive">
          <TriangleAlert className="h-4 w-4 shrink-0" />
          <span>Red flag: sent to Emergency</span>
        </div>
      )}

      {summary.status === "unavailable" ? (
        <p className="text-muted-foreground">
          Summary unavailable. The recorded details below are still accurate.
        </p>
      ) : (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
          <dt className="text-muted-foreground">Complaint</dt>
          <dd>{summary.chief_complaint ?? "-"}</dd>
          <dt className="text-muted-foreground">Duration</dt>
          <dd>{summary.duration ?? "-"}</dd>
          {summary.key_answers.length > 0 && (
            <>
              <dt className="text-muted-foreground">Also said</dt>
              <dd>
                <ul className="flex list-disc flex-col gap-0.5 pl-4">
                  {summary.key_answers.map((answer, i) => (
                    <li key={i}>{answer}</li>
                  ))}
                </ul>
              </dd>
            </>
          )}
        </dl>
      )}

      {summary.patient_words && (
        <figure className="rounded-lg border border-border bg-elevated px-3 py-2">
          <figcaption className="eyebrow !text-[10px]">In the patient&apos;s words</figcaption>
          <blockquote className="mt-1 leading-relaxed">
            &ldquo;{summary.patient_words}&rdquo;
          </blockquote>
        </figure>
      )}

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 border-t border-border pt-3 text-xs">
        <dt className="text-muted-foreground">Recorded symptom</dt>
        <dd>{structured.symptoms ?? "-"}</dd>
        <dt className="text-muted-foreground">Outcome</dt>
        <dd>
          {structured.booking
            ? `${structured.booking.doctor}, ${structured.booking.department}, ${structured.booking.when}`
            : structured.routed_department
              ? `Routed to ${structured.routed_department}`
              : "No booking"}
        </dd>
        {languageLabel(structured.language) && (
          <>
            <dt className="text-muted-foreground">Call language</dt>
            <dd>{languageLabel(structured.language)}</dd>
          </>
        )}
      </dl>
    </div>
  );
}
