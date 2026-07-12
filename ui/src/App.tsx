import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import {
  AnchorType,
  ExploreEdge,
  ExploreNode,
  ExploreResult,
  SignalView,
  demoReset,
  explore,
  listSignals,
} from "./api";

const NODE_COLORS: Record<string, string> = {
  Party: "#4c8dff",
  Property: "#3dbb7e",
  Loan: "#e8a13c",
};
const FLAGGED_COLOR = "#e05252";

interface GraphNode extends ExploreNode {
  x?: number;
  y?: number;
}

export default function App() {
  const [anchorType, setAnchorType] = useState<AnchorType>("party");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<ExploreResult | null>(null);
  const [signals, setSignals] = useState<SignalView[]>([]);
  const [selected, setSelected] = useState<ExploreNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });

  const refreshSignals = useCallback(() => {
    listSignals().then(setSignals).catch(() => setSignals([]));
  }, []);

  useEffect(refreshSignals, [refreshSignals]);

  useEffect(() => {
    const measure = () => {
      const el = containerRef.current;
      if (el) setSize({ width: el.clientWidth, height: el.clientHeight });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const runExplore = useCallback(
    async (type: AnchorType, q: string) => {
      if (!q.trim()) return;
      setError(null);
      setSelected(null);
      setBusy("Exploring…");
      try {
        setResult(await explore(type, q.trim()));
      } catch (e) {
        setResult(null);
        setError((e as Error).message);
      } finally {
        setBusy(null);
      }
      refreshSignals();
    },
    [refreshSignals],
  );

  const onReset = useCallback(async () => {
    if (!window.confirm("Clear the graph and reload the seed dataset?")) return;
    setBusy("Resetting and reseeding (can take a few minutes)…");
    setError(null);
    try {
      await demoReset();
      setResult(null);
      setSelected(null);
      refreshSignals();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }, [refreshSignals]);

  const flaggedParties = useMemo(
    () => new Set((result?.flags ?? []).map((f) => f.partyId)),
    [result],
  );

  const graphData = useMemo(() => {
    if (!result) return { nodes: [], links: [] };
    return {
      nodes: result.nodes.map((n) => ({ ...n })),
      links: result.edges.map((e) => ({ ...e })),
    };
  }, [result]);

  const drawNode = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const flagged = node.nodeType === "Party" && flaggedParties.has(node.id);
      const isAnchor = node.id === result?.anchor.id;
      const r = isAnchor ? 8 : 5;
      ctx.beginPath();
      ctx.arc(node.x!, node.y!, r, 0, 2 * Math.PI);
      ctx.fillStyle = flagged ? FLAGGED_COLOR : NODE_COLORS[node.nodeType];
      ctx.fill();
      if (isAnchor) {
        ctx.lineWidth = 2 / scale;
        ctx.strokeStyle = "#222";
        ctx.stroke();
      }
      if (scale > 1.2) {
        ctx.font = `${11 / scale}px sans-serif`;
        ctx.textAlign = "center";
        ctx.fillStyle = "#333";
        ctx.fillText(node.label, node.x!, node.y! + r + 12 / scale);
      }
    },
    [flaggedParties, result],
  );

  return (
    <div className="layout">
      <header>
        <h1>Party Network POC</h1>
        <button className="danger" onClick={onReset} disabled={busy !== null}>
          Demo reset
        </button>
      </header>
      <aside>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            runExplore(anchorType, query);
          }}
        >
          <label>
            Anchor
            <select
              value={anchorType}
              onChange={(e) => setAnchorType(e.target.value as AnchorType)}
            >
              <option value="party">Party (id or name)</option>
              <option value="loan">Loan (loanRef)</option>
              <option value="property">Property (address)</option>
            </select>
          </label>
          <label>
            Search
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. Patricia Morrison"
            />
          </label>
          <button type="submit" disabled={busy !== null}>
            Explore
          </button>
        </form>

        {busy && <p className="status">{busy}</p>}
        {error && <p className="error">{error}</p>}

        {result && result.guards.length > 0 && (
          <section className="guards">
            <h2>Not expanded (degree guard)</h2>
            {result.guards.map((g) => (
              <p key={g.nodeId}>
                {g.label} — {g.degree} relationships
              </p>
            ))}
          </section>
        )}

        {selected && (
          <section className="details">
            <h2>
              {selected.nodeType}: {selected.label}
            </h2>
            <table>
              <tbody>
                {Object.entries(selected.properties).map(([k, v]) => (
                  <tr key={k}>
                    <td>{k}</td>
                    <td>{Array.isArray(v) ? v.join(", ") : String(v ?? "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <section className="signals">
          <h2>Signals ({signals.length})</h2>
          {signals.length === 0 && <p className="muted">None raised.</p>}
          {signals.map((s) => (
            <div key={s.id} className={`signal ${s.severity.toLowerCase()}`}>
              <strong>{s.patternType}</strong> · {s.severity}
              <p className="muted">{s.attributeId}</p>
              <p>
                {s.relatedPartyIds.map((pid) => (
                  <button
                    key={pid}
                    className="link"
                    onClick={() => runExplore("party", pid)}
                  >
                    {pid.slice(0, 8)}…
                  </button>
                ))}
              </p>
            </div>
          ))}
        </section>
      </aside>
      <main ref={containerRef}>
        {result ? (
          <ForceGraph2D
            width={size.width}
            height={size.height}
            graphData={graphData}
            nodeCanvasObject={drawNode as never}
            nodePointerAreaPaint={(node, color, ctx) => {
              const n = node as GraphNode;
              ctx.beginPath();
              ctx.arc(n.x!, n.y!, 9, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
            }}
            linkLabel={(l) => {
              const e = l as unknown as ExploreEdge;
              return [e.role ?? e.type, e.tier, e.sourceSystem]
                .filter(Boolean)
                .join(" · ");
            }}
            linkDirectionalArrowLength={4}
            linkDirectionalArrowRelPos={1}
            onNodeClick={(node) => setSelected(node as unknown as ExploreNode)}
          />
        ) : (
          <div className="empty">
            <p>Search a party, loan, or property to render its network.</p>
            <p className="muted">
              Try “Patricia Morrison”, loan “MF-811111”, or “777 Risk Avenue,
              Las Vegas, NV 89109”.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
