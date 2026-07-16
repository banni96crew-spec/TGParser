import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MANIFEST_PATH = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "policy-manifest.json",
);

let cachedManifest = null;

export function loadPolicyManifest(manifestPath = MANIFEST_PATH) {
  if (cachedManifest && manifestPath === MANIFEST_PATH) {
    return cachedManifest;
  }
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  if (manifestPath === MANIFEST_PATH) {
    cachedManifest = manifest;
  }
  return manifest;
}

export function resetPolicyManifestCache() {
  cachedManifest = null;
}

export function featureFlag(name, manifest = loadPolicyManifest()) {
  return Boolean(manifest.feature_flags?.[name]);
}

export function eventCapability(eventName, manifest = loadPolicyManifest()) {
  return manifest.events?.[eventName] ?? null;
}

export function isEventMapped(eventName, manifest = loadPolicyManifest()) {
  return eventCapability(eventName, manifest)?.mapped === true;
}

export function verifiedToolIds(manifest = loadPolicyManifest()) {
  const read = new Set(
    (manifest.verified_tool_ids?.read ?? []).map((id) =>
      String(id).split(/[./]/).at(-1).toLowerCase(),
    ),
  );
  const mutation = new Set(
    (manifest.verified_tool_ids?.mutation ?? []).map((id) =>
      String(id).split(/[./]/).at(-1).toLowerCase(),
    ),
  );
  return { read, mutation };
}
