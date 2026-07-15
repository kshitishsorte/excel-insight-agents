import { useRef, useState, DragEvent } from "react";
import { UploadCloud } from "lucide-react";

export function UploadDropzone({ onUpload }: { onUpload: (file: File) => void }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    if (!/\.(xlsx|xls)$/i.test(file.name)) {
      alert("Please choose an .xlsx or .xls file.");
      return;
    }
    onUpload(file);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  };

  return (
    <div className="relative flex flex-1 items-center justify-center overflow-hidden px-6">
      {/* Ambient gradient blobs (CSS-only, slow drift; disabled under reduced-motion) */}
      <div className="ambient-blob animate-blob-drift" style={{ top: "12%", left: "18%" }} />
      <div
        className="ambient-blob animate-blob-drift"
        style={{ bottom: "8%", right: "14%", animationDelay: "-9s", opacity: 0.16 }}
      />

      <div className="relative z-10 w-full max-w-lg text-center">
        <h2 className="mb-2 font-display text-3xl font-600 tracking-tight text-primary">
          Drop a spreadsheet to begin.
        </h2>
        <p className="mb-8 text-sm text-muted">
          The agents will fix the data types, handle missing values, verify each other, and
          surface the insights.
        </p>

        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`cursor-pointer rounded-2xl border-2 border-dashed p-12 transition-colors ${
            dragging ? "border-azure bg-azure/5" : "border-hairline bg-surface/40 hover:border-azure/60"
          }`}
        >
          <UploadCloud size={34} className="mx-auto mb-3 text-azure" />
          <p className="text-sm font-500 text-primary">Drag a file here, or click to browse</p>
          <p className="mt-1 font-mono text-xs text-muted">.xlsx / .xls</p>
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
          />
        </div>
      </div>
    </div>
  );
}
