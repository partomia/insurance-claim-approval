import { useRef, useState } from "react"
import { Upload } from "lucide-react"

import { cn } from "@/lib/utils"

interface FileInputProps {
  accept?: string
  multiple?: boolean
  disabled?: boolean
  placeholder?: string
  className?: string
  onChange?: (files: FileList | null) => void
  onFilesSelected?: (files: File[]) => void
}

function formatFileNames(files: FileList | File[] | null): string {
  if (!files || files.length === 0) return ""
  const list = Array.from(files)
  if (list.length === 1) return list[0].name
  return `${list.length} files selected`
}

export function FileInput({
  accept,
  multiple = false,
  disabled = false,
  placeholder = "Choose file or drag here",
  className,
  onChange,
  onFilesSelected,
}: FileInputProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [selectedLabel, setSelectedLabel] = useState("")

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    setSelectedLabel(formatFileNames(files))
    onChange?.(files)
    onFilesSelected?.(files ? Array.from(files) : [])
  }

  return (
    <div className={cn("space-y-2", className)}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "field-control flex min-h-[88px] w-full cursor-pointer flex-col items-center justify-center gap-2 border-2 border-dashed border-foreground/20 bg-field px-4 py-4 text-center transition-colors",
          "hover:border-primary/40 hover:bg-primary/[0.03]",
          "focus-visible:border-primary/40 focus-visible:ring-[3px] focus-visible:ring-primary/25",
          disabled && "pointer-events-none opacity-50"
        )}
      >
        <Upload className="h-5 w-5 text-muted-foreground" />
        <span className="text-sm font-medium text-foreground">
          {selectedLabel || placeholder}
        </span>
        {!selectedLabel && (
          <span className="text-xs text-muted-foreground">PDF, PNG, or JPG</span>
        )}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        className="sr-only"
        onChange={handleChange}
      />
    </div>
  )
}
