import { useCallback, useEffect, useRef, useState } from "react";

/**
 * A drop target that also stays clickable.
 *
 * Dragging is the natural gesture for documents, but it is not the only one:
 * the real file input underneath keeps the zone reachable by keyboard and by
 * people who would rather browse.
 */
export function DropZone({
  onFiles,
  accept,
  disabled = false,
  children,
}: {
  onFiles: (files: File[]) => void;
  accept: string;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // dragenter and dragleave fire for every child element, so a plain boolean
  // flickers as the pointer crosses the inner text. Counting depth is what
  // makes the highlight stable.
  const depth = useRef(0);

  useEffect(() => {
    // Dropping slightly outside the zone would otherwise make the browser open
    // the file and navigate away from the application, losing everything on
    // screen. Swallowing it everywhere else is the only way to prevent that.
    const swallow = (event: DragEvent) => event.preventDefault();
    window.addEventListener("dragover", swallow);
    window.addEventListener("drop", swallow);
    return () => {
      window.removeEventListener("dragover", swallow);
      window.removeEventListener("drop", swallow);
    };
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      depth.current = 0;
      setDragging(false);
      if (disabled) return;
      const files = Array.from(event.dataTransfer.files);
      if (files.length) onFiles(files);
    },
    [disabled, onFiles],
  );

  return (
    <div
      onDragEnter={(event) => {
        event.preventDefault();
        depth.current += 1;
        if (!disabled) setDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => {
        depth.current -= 1;
        if (depth.current <= 0) setDragging(false);
      }}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className={`cursor-pointer rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${
        dragging
          ? "border-slate-900 bg-slate-100"
          : "border-slate-300 bg-slate-50/60 hover:border-slate-400 hover:bg-slate-50"
      } ${disabled ? "pointer-events-none opacity-50" : ""}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple
        className="sr-only"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          // Cleared so that picking the SAME file again still fires change.
          event.target.value = "";
          if (files.length) onFiles(files);
        }}
      />
      {children}
    </div>
  );
}
