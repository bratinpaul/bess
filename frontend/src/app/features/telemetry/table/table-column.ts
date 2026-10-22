export type ColumnKind = 'timestamp' | 'text' | 'number' | 'alarm';

export interface TableColumn {
  key: string;
  label: string;
  kind: ColumnKind;
  /** Heading the column is listed under in the column selector. */
  group: string;
  /** Always shown; cannot be unticked in the column selector. */
  locked?: boolean;
}

export type TableRow = Record<string, unknown>;
