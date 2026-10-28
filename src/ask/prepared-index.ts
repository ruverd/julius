import type { AskIndex, AskIndexDoc } from "./index-file.js";

interface PreparedAskDoc {
  name: Map<string, number>;
  path: Map<string, number>;
  body: Map<string, number>;
}

const preparedIndexes = new WeakMap<AskIndex, Map<string, AskIndexDoc>>();
const preparedFields = new WeakMap<AskIndexDoc, PreparedAskDoc>();

/** Reuse field maps while the loader retains the same immutable sidecar object. */
export function preparedAskDocs(index: AskIndex): Map<string, AskIndexDoc> {
  const cached = preparedIndexes.get(index);
  if (cached) return cached;
  const docs = new Map(index.docs.map((doc) => [doc.id, doc]));
  preparedIndexes.set(index, docs);
  return docs;
}

export function preparedAskFields(doc: AskIndexDoc): PreparedAskDoc {
  const cached = preparedFields.get(doc);
  if (cached) return cached;
  const fields = {
    name: new Map(doc.name),
    path: new Map(doc.path),
    body: new Map(doc.body),
  };
  preparedFields.set(doc, fields);
  return fields;
}
