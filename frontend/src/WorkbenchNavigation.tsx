import { Captions, Download, FileText, Image } from "lucide-react";
import type { KeyboardEvent, ReactNode } from "react";

import { statusText } from "./constants";
import type { JobState, JobSummary } from "./types";

export type WorkbenchTab = "note" | "subtitle" | "frame" | "files";

type Props = {
  active: WorkbenchTab;
  job: JobState;
  summary: JobSummary | null;
  onChange: (tab: WorkbenchTab) => void;
};

const tabs: Array<{ id: WorkbenchTab; label: string; icon: ReactNode }> = [
  { id: "note", label: "笔记审核", icon: <FileText size={15} /> },
  { id: "subtitle", label: "字幕审核", icon: <Captions size={15} /> },
  { id: "frame", label: "配图审核", icon: <Image size={15} /> },
  { id: "files", label: "文件与日志", icon: <Download size={15} /> }
];

export function WorkbenchNavigation({ active, job, summary, onChange }: Props) {
  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (index + 1) % tabs.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (index - 1 + tabs.length) % tabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = tabs.length - 1;
    }
    if (nextIndex === null) {
      return;
    }
    event.preventDefault();
    onChange(tabs[nextIndex].id);
    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    buttons?.[nextIndex]?.focus();
  }

  return (
    <>
      <div className="task-summary">
        <div className="task-summary-copy">
          <strong>{summary?.title || summary?.original_filename || "当前任务"}</strong>
          <span>
            {statusText[job.status]} · {job.step || "等待处理"} · {Math.round(job.progress)}%
          </span>
        </div>
      </div>
      <div className="workbench-tabs" role="tablist" aria-label="结果工作区">
        {tabs.map((tab, index) => (
          <button
            aria-selected={active === tab.id}
            className={active === tab.id ? "active" : ""}
            key={tab.id}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
            role="tab"
            tabIndex={active === tab.id ? 0 : -1}
            type="button"
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>
    </>
  );
}
