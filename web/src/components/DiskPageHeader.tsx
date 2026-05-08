import type { ReactNode } from "react";
import { DiskUsageBar } from "@/components/DiskUsageBar";
import { ResourceLabel } from "@/components/ResourceLabel";
import { DISK_TITLE } from "@/lib/resourceLabels";

export function DiskPageHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="px-4 py-3 border-b border-border flex gap-5 items-center flex-wrap text-[10px] text-text-dim font-mono">
      <h1 className="text-text text-[14px] font-medium">
        <ResourceLabel resource="disk" label={DISK_TITLE} size={15} />
      </h1>
      {children && (
        <div className="flex items-center gap-5 flex-wrap min-w-0">
          {children}
        </div>
      )}
      <div className="ml-auto shrink-0">
        <DiskUsageBar />
      </div>
    </header>
  );
}
