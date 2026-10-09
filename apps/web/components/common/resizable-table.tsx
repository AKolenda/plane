/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, ReactNode } from "react";
import { cn } from "@plane/utils";

export type TResizableColumn = {
  key: string;
  label: string;
  /** Width the column starts at and returns to on a divider double-click. */
  width: number;
  minWidth?: number;
  align?: "start" | "end";
  /** Hide the visible header text (an actions column) while keeping it for assistive tech. */
  hideLabel?: boolean;
};

const DEFAULT_MIN_WIDTH = 64;
const KEYBOARD_STEP = 16;

/** Makes a form control (a select trigger, an input) fill its cell instead of its own minimum width. */
export const CELL_CONTROL_CLASS = "w-full min-w-0 *:w-full *:min-w-0!";

export const TABLE_CELL_CLASS = "h-11 truncate border-b border-subtle px-3 py-1.5 align-middle text-body-xs-regular";

function ColumnResizeHandle(props: {
  label: string;
  width: number;
  minWidth: number;
  onResize: (width: number) => void;
  onReset: () => void;
}) {
  const { label, width, minWidth, onResize, onReset } = props;
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { startX: event.clientX, startWidth: width };
  };
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    onResize(Math.max(minWidth, drag.current.startWidth + event.clientX - drag.current.startX));
  };
  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") onResize(Math.max(minWidth, width - KEYBOARD_STEP));
    else if (event.key === "ArrowRight") onResize(width + KEYBOARD_STEP);
    else if (event.key === "Enter") onReset();
    else return;
    event.preventDefault();
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(width)}
      aria-valuemin={minWidth}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onDoubleClick={onReset}
      onKeyDown={handleKeyDown}
      className="group/resize absolute inset-y-0 -right-1.5 z-10 flex w-3 cursor-col-resize touch-none justify-center outline-none"
    >
      <span className="group-hover/resize:bg-accent-strong group-focus-visible/resize:bg-accent-strong h-full w-px bg-transparent" />
    </div>
  );
}

/**
 * A record table with fixed column widths that the header dividers resize. Dragging a divider
 * sets the width of the column to its left; double-clicking it restores that column's default.
 * Rows are the caller's `<tr>` elements with `TABLE_CELL_CLASS` cells.
 */
export function ResizableTable(props: { columns: TResizableColumn[]; children: ReactNode; resizeLabel: string }) {
  const { columns, children, resizeLabel } = props;
  const [widths, setWidths] = useState<Record<string, number>>({});

  const widthOf = useCallback((column: TResizableColumn) => widths[column.key] ?? column.width, [widths]);
  const setWidth = (key: string, width: number) => setWidths((current) => ({ ...current, [key]: width }));
  const resetWidth = (key: string) =>
    setWidths((current) => {
      const { [key]: _removed, ...rest } = current;
      return rest;
    });
  const totalWidth = columns.reduce((sum, column) => sum + widthOf(column), 0);

  return (
    <div className="w-full overflow-x-auto rounded-lg border border-subtle bg-surface-1">
      <table className="table-fixed border-collapse text-primary" style={{ width: totalWidth, minWidth: "100%" }}>
        <colgroup>
          {columns.map((column) => (
            <col key={column.key} style={{ width: widthOf(column) }} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {columns.map((column, index) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  "relative h-11 truncate border-b border-subtle bg-layer-1 px-3 py-2 text-caption-md-semibold text-tertiary",
                  column.align === "end" ? "text-end" : "text-start"
                )}
              >
                <span className={cn({ "sr-only": column.hideLabel })}>{column.label}</span>
                {index < columns.length - 1 && (
                  <ColumnResizeHandle
                    label={`${resizeLabel}: ${column.label}`}
                    width={widthOf(column)}
                    minWidth={column.minWidth ?? DEFAULT_MIN_WIDTH}
                    onResize={(width) => setWidth(column.key, width)}
                    onReset={() => resetWidth(column.key)}
                  />
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
