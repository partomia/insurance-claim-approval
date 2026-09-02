import type { ChangeEvent } from "react";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const INCIDENT_TYPES = [
  { value: "COLLISION", label: "Collision" },
  { value: "THEFT", label: "Theft" },
  { value: "VANDALISM", label: "Vandalism" },
  { value: "FIRE", label: "Fire" },
  { value: "NATURAL_DISASTER", label: "Natural disaster" },
  { value: "GLASS_ONLY", label: "Glass only" },
  { value: "THIRD_PARTY_LIABILITY", label: "Third-party liability" },
  { value: "OTHER", label: "Other" },
];

export interface Step1MotorState {
  incidentType: string;
  incidentDescription: string;
  incidentDatetime: string;
  location: string;
  claimAmount: string;
  vehicleMake: string;
  vehicleModel: string;
  vehicleYear: string;
  vin: string;
  licensePlate: string;
  odometerKm: string;
  driverLicenseNumber: string;
  driverLicenseClass: string;
  thirdPartyInvolved: boolean;
  injuriesReported: boolean;
  towRequired: boolean;
}

interface Step1Props extends Step1MotorState {
  setIncidentType: (v: string) => void;
  setIncidentDescription: (v: string) => void;
  setIncidentDatetime: (v: string) => void;
  setLocation: (v: string) => void;
  setClaimAmount: (v: string) => void;
  setVehicleMake: (v: string) => void;
  setVehicleModel: (v: string) => void;
  setVehicleYear: (v: string) => void;
  setVin: (v: string) => void;
  setLicensePlate: (v: string) => void;
  setOdometerKm: (v: string) => void;
  setDriverLicenseNumber: (v: string) => void;
  setDriverLicenseClass: (v: string) => void;
  setThirdPartyInvolved: (v: boolean) => void;
  setInjuriesReported: (v: boolean) => void;
  setTowRequired: (v: boolean) => void;
  onContinue: () => void;
  loading: boolean;
}

export function Step1IncidentDetails(props: Step1Props) {
  const {
    incidentType,
    incidentDescription,
    incidentDatetime,
    location,
    claimAmount,
    vehicleMake,
    vehicleModel,
    vehicleYear,
    vin,
    licensePlate,
    odometerKm,
    driverLicenseNumber,
    driverLicenseClass,
    thirdPartyInvolved,
    injuriesReported,
    towRequired,
    setIncidentType,
    setIncidentDescription,
    setIncidentDatetime,
    setLocation,
    setClaimAmount,
    setVehicleMake,
    setVehicleModel,
    setVehicleYear,
    setVin,
    setLicensePlate,
    setOdometerKm,
    setDriverLicenseNumber,
    setDriverLicenseClass,
    setThirdPartyInvolved,
    setInjuriesReported,
    setTowRequired,
    onContinue,
    loading,
  } = props;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Step 1 — Incident & Vehicle Details</h2>
        <p className="text-sm text-muted-foreground">
          Tell us about the incident, the vehicle involved, and the driver. We'll create a draft
          motor claim; you'll attach your policy in Step 2.
        </p>
      </div>

      <section className="space-y-4">
        <h3 className="text-sm font-medium text-muted-foreground">Incident</h3>

        <FormField label="Incident type">
          <select
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            value={incidentType}
            onChange={(e) => setIncidentType(e.target.value)}
          >
            {INCIDENT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="What happened?">
          <Textarea
            value={incidentDescription}
            onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setIncidentDescription(e.target.value)}
            placeholder="Describe the accident — how, where, other vehicles or objects involved…"
            rows={4}
          />
        </FormField>

        <div className="grid grid-cols-2 gap-4">
          <FormField label="Date & time">
            <Input
              type="datetime-local"
              value={incidentDatetime}
              onChange={(e) => setIncidentDatetime(e.target.value)}
            />
          </FormField>
          <FormField label="Location">
            <Input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Mumbai, Maharashtra"
            />
          </FormField>
        </div>

        <FormField label="Estimated repair / replacement cost (₹)">
          <Input
            type="number"
            value={claimAmount}
            onChange={(e) => setClaimAmount(e.target.value)}
            placeholder="45000"
          />
        </FormField>

        <div className="flex flex-wrap gap-4 pt-1">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={thirdPartyInvolved}
              onChange={(e) => setThirdPartyInvolved(e.target.checked)}
            />
            Third party involved
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={injuriesReported}
              onChange={(e) => setInjuriesReported(e.target.checked)}
            />
            Injuries reported
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={towRequired}
              onChange={(e) => setTowRequired(e.target.checked)}
            />
            Vehicle needed towing
          </label>
        </div>
      </section>

      <section className="space-y-4">
        <h3 className="text-sm font-medium text-muted-foreground">Vehicle</h3>
        <div className="grid grid-cols-3 gap-4">
          <FormField label="Make">
            <Input value={vehicleMake} onChange={(e) => setVehicleMake(e.target.value)} placeholder="Toyota" />
          </FormField>
          <FormField label="Model">
            <Input value={vehicleModel} onChange={(e) => setVehicleModel(e.target.value)} placeholder="Camry" />
          </FormField>
          <FormField label="Year">
            <Input
              type="number"
              value={vehicleYear}
              onChange={(e) => setVehicleYear(e.target.value)}
              placeholder="2022"
            />
          </FormField>
        </div>
        <div className="grid grid-cols-3 gap-4">
          <FormField label="VIN / Chassis #">
            <Input value={vin} onChange={(e) => setVin(e.target.value)} placeholder="1HGBH41JXMN109186" />
          </FormField>
          <FormField label="Licence plate">
            <Input
              value={licensePlate}
              onChange={(e) => setLicensePlate(e.target.value)}
              placeholder="MH-01-AB-1234"
            />
          </FormField>
          <FormField label="Odometer (km)">
            <Input
              type="number"
              value={odometerKm}
              onChange={(e) => setOdometerKm(e.target.value)}
              placeholder="42500"
            />
          </FormField>
        </div>
      </section>

      <section className="space-y-4">
        <h3 className="text-sm font-medium text-muted-foreground">Driver at the time of incident</h3>
        <div className="grid grid-cols-2 gap-4">
          <FormField label="Driver's licence number">
            <Input
              value={driverLicenseNumber}
              onChange={(e) => setDriverLicenseNumber(e.target.value)}
              placeholder="DL-1234-56789"
            />
          </FormField>
          <FormField label="Licence class (optional)">
            <Input
              value={driverLicenseClass}
              onChange={(e) => setDriverLicenseClass(e.target.value)}
              placeholder="LMV / MCWG"
            />
          </FormField>
        </div>
      </section>

      <div className="flex justify-end gap-3 border-t pt-4">
        <Button onClick={onContinue} disabled={loading}>
          {loading ? "Creating draft..." : "Continue →"}
        </Button>
      </div>
    </div>
  );
}
