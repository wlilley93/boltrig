export interface StepperButtonsProps {
  value: number;
  step: number;
  disabled: boolean;
  atMin: boolean;
  atMax: boolean;
  commit: (n: number) => void;
}

export function StepperButtons({ value, step, disabled, atMin, atMax, commit }: StepperButtonsProps) {
  return (
    <>
      <button
        type="button"
        className="btn btn--sm ux-stepper__btn"
        aria-label="Decrease"
        disabled={disabled || atMin}
        onClick={() => commit(value - step)}
      >
        -
      </button>
      <button
        type="button"
        className="btn btn--sm ux-stepper__btn"
        aria-label="Increase"
        disabled={disabled || atMax}
        onClick={() => commit(value + step)}
      >
        +
      </button>
    </>
  );
}
