"use client";

import type React from "react";

import { useCallback, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Upload, X, FileText } from "lucide-react";

interface UploadedFile {
  name: string;
  content: string;
}

interface FileUploadProps {
  onFileSelect: (file: UploadedFile | null) => void;
  disabled: boolean;
}

const ACCEPTED_EXTENSIONS = [".json", ".xml", ".txt", ".log", ".har"];
const ACCEPT_STRING = ACCEPTED_EXTENSIONS.join(",");

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileUpload({ onFileSelect, disabled }: FileUploadProps) {
  const [file, setFile] = useState<{ name: string; size: number } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const readFile = useCallback(
    (f: File) => {
      const reader = new FileReader();
      reader.onload = () => {
        const content = reader.result as string;
        setFile({ name: f.name, size: f.size });
        onFileSelect({ name: f.name, content });
      };
      reader.readAsText(f);
    },
    [onFileSelect]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      const dropped = e.dataTransfer.files[0];
      if (dropped) readFile(dropped);
    },
    [disabled, readFile]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files?.[0];
      if (selected) readFile(selected);
    },
    [readFile]
  );

  const handleRemove = useCallback(() => {
    setFile(null);
    onFileSelect(null);
    if (inputRef.current) inputRef.current.value = "";
  }, [onFileSelect]);

  return (
    <div className="space-y-2">
      <Label className="text-black font-medium">SDK Log File</Label>
      {file ? (
        <div className="flex items-center justify-between p-3 border border-gray-300 rounded-md bg-gray-50">
          <div className="flex items-center gap-2 min-w-0">
            <FileText className="h-4 w-4 shrink-0 text-gray-600" />
            <div className="min-w-0">
              <p className="text-sm text-black truncate">{file.name}</p>
              <p className="text-xs text-gray-500">{formatFileSize(file.size)}</p>
            </div>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleRemove}
            disabled={disabled}
            className="shrink-0 h-8 w-8 p-0"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ) : (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            if (!disabled) setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => !disabled && inputRef.current?.click()}
          className={`flex flex-col items-center justify-center gap-2 p-4 border-2 border-dashed rounded-md cursor-pointer transition-colors ${
            dragOver
              ? "border-[#00BCEBFF] bg-[#00BCEB10]"
              : "border-gray-300 hover:border-gray-400"
          } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          <Upload className="h-5 w-5 text-gray-400" />
          <p className="text-xs text-gray-500 text-center">
            Drop file here or click to browse
          </p>
          <p className="text-xs text-gray-400">
            .json, .xml, .txt, .log, .har
          </p>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT_STRING}
            onChange={handleChange}
            className="hidden"
          />
        </div>
      )}
    </div>
  );
}
