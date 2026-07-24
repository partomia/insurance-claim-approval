import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatEscalationList } from "@/lib/escalationLabels";

interface EscalationFlagsCardProps {
  messages: string[];
  flags?: string[];
  assignedAgent?: string | null;
  onAssign: () => void;
  title?: string;
}

export function EscalationFlagsCard({
  messages,
  flags,
  assignedAgent,
  onAssign,
  title = "Needs your attention",
}: EscalationFlagsCardProps) {
  const items = formatEscalationList(messages, flags);
  if (items.length === 0) return null;

  return (
    <Card className="shadow-sm ring-warning-border bg-warning-subtle">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base text-warning">
          <AlertTriangle className="h-5 w-5" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="space-y-2">
          {items.map((msg) => (
            <li key={msg} className="flex items-start gap-2 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <span>{msg}</span>
            </li>
          ))}
        </ul>
        {!assignedAgent && (
          <Button onClick={onAssign} className="w-full sm:w-auto">
            Assign Claim Expert
          </Button>
        )}
        {assignedAgent && (
          <p className="text-sm text-muted-foreground">
            Assigned to <span className="font-medium text-foreground">{assignedAgent}</span>
          </p>
        )}
      </CardContent>
    </Card>
  );
}
