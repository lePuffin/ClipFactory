/** JSON value edited by the generic settings/profile form editors. */
export type EditorValue = string | number | boolean | null | EditorValue[] | { [key: string]: EditorValue };
export type EditorObject = { [key: string]: EditorValue };

export function isEditorObject(value: unknown): value is EditorObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
