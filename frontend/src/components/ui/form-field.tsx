import * as React from "react"

import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"

interface FormFieldProps {
  label?: React.ReactNode
  htmlFor?: string
  description?: React.ReactNode
  className?: string
  children: React.ReactNode
}

export function FormField({ label, htmlFor, description, className, children }: FormFieldProps) {
  return (
    <div className={cn("space-y-2", className)}>
      {label ? <Label htmlFor={htmlFor}>{label}</Label> : null}
      {children}
      {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
    </div>
  )
}
