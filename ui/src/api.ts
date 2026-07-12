// Typed client for the POC API (contracts in docs/contracts/).

export type NodeType = "Party" | "Property" | "Loan";

export interface ExploreNode {
  id: string;
  nodeType: NodeType;
  label: string;
  hop: number;
  properties: Record<string, unknown>;
}

export interface ExploreEdge {
  source: string;
  target: string;
  type: "CONNECTED_TO" | "HAS_ROLE_ON";
  role: string | null;
  tier: string | null;
  edgeSource: string | null;
  sourceSystem: string | null;
  eventId: string | null;
}

export interface GuardMarker {
  nodeId: string;
  nodeType: NodeType;
  label: string;
  degree: number;
  expanded: false;
}

export interface SignalFlag {
  partyId: string;
  signalId: string;
  patternType: string;
}

export interface ExploreResult {
  anchor: ExploreNode;
  nodes: ExploreNode[];
  edges: ExploreEdge[];
  guards: GuardMarker[];
  flags: SignalFlag[];
}

export interface SignalView {
  id: string;
  patternType: string;
  severity: string;
  status: string;
  relatedPartyIds: string[];
  evidencePath: string[];
  attributeId: string;
  causationEventId: string;
  raisedAt: string;
}

export type AnchorType = "party" | "loan" | "property";

export async function explore(
  anchorType: AnchorType,
  q: string,
): Promise<ExploreResult> {
  const params = new URLSearchParams({ anchorType, q });
  const resp = await fetch(`/explore?${params}`);
  if (resp.status === 404) throw new Error(`No ${anchorType} found for "${q}"`);
  if (!resp.ok) throw new Error(`Explore failed: ${resp.status}`);
  return resp.json();
}

export async function listSignals(): Promise<SignalView[]> {
  const resp = await fetch("/signals");
  if (!resp.ok) throw new Error(`Signals failed: ${resp.status}`);
  return resp.json();
}

export async function demoReset(): Promise<Record<string, unknown>> {
  const resp = await fetch("/admin/reset", { method: "POST" });
  if (!resp.ok) throw new Error(`Reset failed: ${resp.status}`);
  return resp.json();
}
