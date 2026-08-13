import { cn } from "@/lib/utils";

type PredictionMatrixProps = {
  className?: string;
  activeCell?: 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
  decorative?: boolean;
};

/**
 * Prediction Matrix — a secondary visual primitive for model/feature surfaces.
 * The highlighted terminal cell indicates the selected forecast, never model certainty.
 */
export function PredictionMatrix({
  className,
  activeCell = 8,
  decorative = true,
}: PredictionMatrixProps) {
  const cells = [0, 1, 3, 4, 5, 7, 8] as const;
  return (
    <span
      className={cn("prediction-matrix", className)}
      aria-hidden={decorative ? true : undefined}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : "Prediction matrix"}
    >
      {cells.map((cell) => (
        <span
          key={cell}
          className={cn("prediction-matrix__cell", cell === activeCell && "prediction-matrix__cell--active")}
          style={{ gridArea: `${Math.floor(cell / 3) + 1} / ${(cell % 3) + 1}` }}
        />
      ))}
    </span>
  );
}
