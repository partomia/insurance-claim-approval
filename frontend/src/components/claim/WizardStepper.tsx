import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

const STEPS = [
  { num: 1, label: "Incident & Vehicle" },
  { num: 2, label: "Motor Policy" },
  { num: 3, label: "Evidence & RC" },
  { num: 4, label: "Review & Submit" },
];

interface WizardStepperProps {
  currentStep: number;
}

export function WizardStepper({ currentStep }: WizardStepperProps) {
  const activeLabel =
    STEPS.find((s) => s.num === currentStep)?.label ?? "";
  const progress = Math.min(
    100,
    Math.max(0, ((currentStep - 1) / (STEPS.length - 1)) * 100),
  );

  return (
    <div className="mb-8">
      {/* Mobile: compact progress bar + label. */}
      <div className="sm:hidden">
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-medium text-foreground">
            Step {currentStep} of {STEPS.length}
          </span>
          <span className="text-muted-foreground">{activeLabel}</span>
        </div>
        <div
          className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={currentStep}
          aria-valuemin={1}
          aria-valuemax={STEPS.length}
          aria-label={`Step ${currentStep} of ${STEPS.length}: ${activeLabel}`}
        >
          <div
            className="h-full rounded-full bg-primary transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Desktop: full stepper. */}
      <ol
        role="list"
        aria-label="Motor claim submission steps"
        className="hidden items-center px-2 sm:flex"
      >
        {STEPS.map((step, i) => {
          const isComplete = currentStep > step.num;
          const isCurrent = currentStep === step.num;
          return (
            <li
              key={step.num}
              className="flex flex-1 items-center"
              aria-current={isCurrent ? "step" : undefined}
            >
              <div className="flex flex-1 flex-col items-center">
                <div
                  className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors",
                    isComplete &&
                      "border-primary bg-primary text-primary-foreground",
                    isCurrent &&
                      "border-primary bg-background text-primary ring-4 ring-primary/15",
                    !isComplete &&
                      !isCurrent &&
                      "border-border bg-background text-muted-foreground",
                  )}
                >
                  {isComplete ? (
                    <Check className="h-4 w-4" strokeWidth={3} />
                  ) : (
                    step.num
                  )}
                </div>
                <span
                  className={cn(
                    "mt-2 text-center text-xs",
                    isCurrent
                      ? "font-medium text-foreground"
                      : isComplete
                        ? "text-foreground"
                        : "text-muted-foreground",
                  )}
                >
                  {step.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div
                  aria-hidden
                  className={cn(
                    "mb-6 h-0.5 flex-1 mx-2 transition-colors",
                    isComplete ? "bg-primary" : "bg-border",
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
