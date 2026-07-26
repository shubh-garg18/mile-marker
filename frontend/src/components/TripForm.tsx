import { useId, useState } from "react";

import type { TripPlanRequest } from "../types/trip";

interface TripFormProps {
  onSubmit: (request: TripPlanRequest) => void;
  isPlanning: boolean;
  /** Field named by the error envelope, so the message lands where the fault is. */
  errorField: string | null;
  errorMessage: string | null;
}

const EXAMPLE: TripPlanRequest = {
  current_location: "Dallas, TX",
  pickup_location: "Oklahoma City, OK",
  dropoff_location: "Denver, CO",
  current_cycle_used_hours: 12.5,
};

export default function TripForm({
  onSubmit,
  isPlanning,
  errorField: serverErrorField,
  errorMessage: serverErrorMessage,
}: TripFormProps) {
  const [currentLocation, setCurrentLocation] = useState(EXAMPLE.current_location);
  const [pickupLocation, setPickupLocation] = useState(EXAMPLE.pickup_location);
  const [dropoffLocation, setDropoffLocation] = useState(EXAMPLE.dropoff_location);
  const [cycleUsed, setCycleUsed] = useState(String(EXAMPLE.current_cycle_used_hours));
  const [startDatetime, setStartDatetime] = useState("");

  const [localError, setLocalError] = useState<{ field: string; message: string } | null>(null);

  // A locally-caught fault takes precedence. It describes what is on screen now,
  // whereas the server's error describes the request that was last sent.
  const errorField = localError?.field ?? serverErrorField;
  const errorMessage = localError?.message ?? serverErrorMessage;

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    // Number("") is 0, so a cleared field would otherwise plan a trip against
    // zero cycle hours and look perfectly successful.
    if (cycleUsed.trim() === "" || Number.isNaN(Number(cycleUsed))) {
      setLocalError({
        field: "current_cycle_used_hours",
        message: "Enter how many hours of the 70-hour cycle are already used.",
      });
      return;
    }
    setLocalError(null);
    onSubmit({
      current_location: currentLocation,
      pickup_location: pickupLocation,
      dropoff_location: dropoffLocation,
      current_cycle_used_hours: Number(cycleUsed),
      ...(startDatetime ? { start_datetime: `${startDatetime}:00` } : {}),
    });
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      <Field
        label="Current location"
        name="current_location"
        value={currentLocation}
        onChange={setCurrentLocation}
        placeholder="Dallas, TX"
        errorField={errorField}
        errorMessage={errorMessage}
        disabled={isPlanning}
      />
      <Field
        label="Pickup location"
        name="pickup_location"
        value={pickupLocation}
        onChange={setPickupLocation}
        placeholder="Oklahoma City, OK"
        errorField={errorField}
        errorMessage={errorMessage}
        disabled={isPlanning}
      />
      <Field
        label="Dropoff location"
        name="dropoff_location"
        value={dropoffLocation}
        onChange={setDropoffLocation}
        placeholder="Denver, CO"
        errorField={errorField}
        errorMessage={errorMessage}
        disabled={isPlanning}
      />
      <Field
        label="Cycle used"
        hint="hours of the 70-hour / 8-day limit already spent"
        name="current_cycle_used_hours"
        type="number"
        inputMode="decimal"
        min={0}
        max={70}
        step={0.25}
        value={cycleUsed}
        onChange={setCycleUsed}
        placeholder="12.5"
        errorField={errorField}
        errorMessage={errorMessage}
        disabled={isPlanning}
      />
      <Field
        label="Departure"
        hint="optional, defaults to 08:00 tomorrow"
        name="start_datetime"
        type="datetime-local"
        value={startDatetime}
        onChange={setStartDatetime}
        errorField={errorField}
        errorMessage={errorMessage}
        disabled={isPlanning}
      />

      <button
        type="submit"
        disabled={isPlanning}
        className="mt-1 rounded-sm bg-signal px-4 py-2.5 font-display text-sm font-semibold tracking-wide text-console uppercase transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isPlanning ? "Planning…" : "Plan trip"}
      </button>
    </form>
  );
}

interface FieldProps {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  errorField: string | null;
  errorMessage: string | null;
  disabled: boolean;
  hint?: string;
  type?: string;
  placeholder?: string;
  inputMode?: "decimal";
  min?: number;
  max?: number;
  step?: number;
}

function Field({
  label,
  name,
  value,
  onChange,
  errorField,
  errorMessage,
  disabled,
  hint,
  type = "text",
  ...inputProps
}: FieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const isFaulty = errorField === name;

  // Both the hint and the error are announced. Describing only the error left a
  // screen-reader user never hearing that the departure field is optional.
  const describedBy = [hint ? hintId : null, isFaulty ? errorId : null].filter(Boolean).join(" ");

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="font-display text-xs tracking-widest text-steel uppercase">
        {label}
      </label>
      {hint ? (
        <span id={hintId} className="-mt-1 text-xs text-steel">
          {hint}
        </span>
      ) : null}
      <input
        {...inputProps}
        id={id}
        name={name}
        type={type}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={isFaulty || undefined}
        aria-describedby={describedBy || undefined}
        className={`rounded-sm border bg-console px-3 py-2 font-data text-sm text-white placeholder:text-steel disabled:opacity-60 ${
          isFaulty ? "border-flag" : "border-hairline focus:border-signal"
        }`}
      />
      {isFaulty && errorMessage ? (
        <p id={errorId} role="alert" className="text-xs leading-snug text-flag">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
