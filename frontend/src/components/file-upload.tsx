"use client";

import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { CloudUpload, File, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface FileUploadProps {
  onFileSelect: (file: File | null) => void;
}

/** Gold/dark dropzone, styled per the MinedTv UI spec's card + button tokens. */
export function FileUpload({ onFileSelect }: FileUploadProps) {
  const [file, setFile] = useState<File | null>(null);

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      if (acceptedFiles.length > 0) {
        const selectedFile = acceptedFiles[0];
        setFile(selectedFile);
        onFileSelect(selectedFile);
      }
    },
    [onFileSelect]
  );

  const removeFile = (e: React.MouseEvent) => {
    e.stopPropagation();
    setFile(null);
    onFileSelect(null);
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    maxFiles: 1,
    accept: { "video/*": [] },
  });

  return (
    <div
      {...getRootProps()}
      className={cn(
        "flex min-h-[280px] cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-12 text-center transition-colors duration-200",
        isDragActive
          ? "border-[var(--mtv-gold)] bg-[var(--mtv-gold)]/10"
          : "border-[var(--mtv-divider)] bg-[var(--mtv-surface)] hover:border-[var(--mtv-gold)]/50 hover:bg-[var(--mtv-surface-high)]/40"
      )}
    >
      <input {...getInputProps()} />

      {file ? (
        <div className="relative flex w-full max-w-md items-center gap-4 rounded-xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface-high)] p-4">
          <div className="rounded-full bg-[var(--mtv-gold)]/15 p-2">
            <File className="h-6 w-6 text-[var(--mtv-gold)]" />
          </div>
          <div className="min-w-0 flex-1 text-left">
            <p className="truncate text-sm font-medium text-[var(--mtv-text)]">{file.name}</p>
            <p className="text-xs text-[var(--mtv-text-2)]">
              {(file.size / (1024 * 1024)).toFixed(2)} MB
            </p>
          </div>
          <button
            type="button"
            onClick={removeFile}
            className="shrink-0 rounded-full p-1.5 text-[var(--mtv-text-2)] transition-colors hover:bg-[var(--mtv-red)]/15 hover:text-[var(--mtv-red)]"
            aria-label="Remove selected file"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <>
          <div className="mb-4 rounded-full bg-[var(--mtv-gold)]/12 p-4">
            <CloudUpload className="h-8 w-8 text-[var(--mtv-gold)]" />
          </div>
          <h3 className="mb-1 text-lg font-semibold text-[var(--mtv-text)]">
            {isDragActive ? "Drop the video here" : "Drag & drop your video here"}
          </h3>
          <p className="mb-6 text-sm text-[var(--mtv-text-2)]">or click to browse from your computer</p>
          <span className="pointer-events-none inline-flex items-center justify-center rounded-xl bg-[var(--mtv-gold)] px-5 py-2.5 text-sm font-bold text-[var(--mtv-on-gold)]">
            Select video
          </span>
        </>
      )}
    </div>
  );
}
