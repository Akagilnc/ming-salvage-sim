import React from "react";
import { Eraser, MapPinned, Move, Pencil, RotateCcw, Shield, ZoomIn, ZoomOut } from "lucide-react";
import { EXTERNAL_PATH_GROUPS, MAP_VIEW_BOX, REGION_PATH_GROUPS } from "../mapPaths";
import { labelPower, monthlyAmount } from "../format";
import type { ExternalPathRenderItem, MapNode, RegionPathRenderItem, SvgLabelPosition, TerrainTransform } from "../types";

export const MING_MAP_COLOR = "#4f8a57";

export const UNREST_MAP_COLOR = "#b83a31";

export const EXTERNAL_MAP_COLOR = "#5f6366";

export const DEFAULT_MAP_COLOR = EXTERNAL_MAP_COLOR;

export const UNREST_DANGER_THRESHOLD = 60;

export const MING_MAP_OPACITY = 0.2;

export const EXTERNAL_MAP_OPACITY = 0.3;

export const MAP_DISPLAY_POWER_OVERRIDES: Record<string, string> = {
  // 崇祯元年辽西只剩山海关外宁锦前线，不能按关内省份红色处理。
  liaodong: "ming_frontier",
};

export const THEATER_ONLY_REGION_IDS = new Set(["liaodong"]);

export const THEATER_COORD_STORAGE_KEY = "ming-map-theater-coords";

export const MAP_PENCIL_STORAGE_KEY = "ming-map-pencil-line";

export const MAP_TERRAIN_STORAGE_KEY = "ming-map-terrain-transform-v3";

export const DEFAULT_TERRAIN_TRANSFORM: TerrainTransform = {
  x: 840.22,
  y: 83.48,
  width: 276,
  height: 206,
};

export function getRegionMapColor(region: RegionPathRenderItem) {
  if (region.controlledBy !== "ming") return EXTERNAL_MAP_COLOR;
  if (region.unrest > UNREST_DANGER_THRESHOLD) return UNREST_MAP_COLOR;
  return MING_MAP_COLOR;
}

export function getRegionMapOpacity(region: RegionPathRenderItem) {
  return region.controlledBy === "ming" ? MING_MAP_OPACITY : EXTERNAL_MAP_OPACITY;
}

export function GrandMap({ nodes, selectedId, onSelect }: { nodes: MapNode[]; selectedId: string; onSelect: (id: string) => void }) {
  const viewportRef = React.useRef<HTMLDivElement | null>(null);
  const mapTileRef = React.useRef<HTMLDivElement | null>(null);
  const svgRef = React.useRef<SVGSVGElement | null>(null);
  const didCenterRef = React.useRef(false);
  const viewBoxParts = React.useMemo(() => MAP_VIEW_BOX.split(/\s+/).map(Number), []);
  const defaultTerrainTransform = DEFAULT_TERRAIN_TRANSFORM;

  // 坐标取点工具：URL 加 ?coords=1 开启。点地图打印 x/y% 与 SVG viewBox 坐标。
  const coordPick = typeof window !== "undefined" && new URLSearchParams(window.location.search).has("coords");
  const [pick, setPick] = React.useState<{ x: number; y: number; svgX: number; svgY: number; label?: string } | null>(null);
  const [draggedTheaters, setDraggedTheaters] = React.useState<Record<string, { x: number; y: number }>>(() => {
    if (typeof window === "undefined") return {};
    try {
      const raw = window.localStorage.getItem(THEATER_COORD_STORAGE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw) as Record<string, { x: number; y: number }>;
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  });
  const [pencilMode, setPencilMode] = React.useState(false);
  const [terrainMode, setTerrainMode] = React.useState(coordPick);
  const [terrainTransform, setTerrainTransform] = React.useState<TerrainTransform>(() => {
    if (typeof window === "undefined") return defaultTerrainTransform;
    try {
      const raw = window.localStorage.getItem(MAP_TERRAIN_STORAGE_KEY);
      if (!raw) return defaultTerrainTransform;
      const parsed = JSON.parse(raw) as TerrainTransform;
      if (
        parsed &&
        Number.isFinite(parsed.x) &&
        Number.isFinite(parsed.y) &&
        Number.isFinite(parsed.width) &&
        Number.isFinite(parsed.height) &&
        parsed.width > 0 &&
        parsed.height > 0
      ) {
        return parsed;
      }
    } catch {}
    return defaultTerrainTransform;
  });
  const [pencilLine, setPencilLine] = React.useState<Array<{ x: number; y: number; svgX: number; svgY: number }>>(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = window.localStorage.getItem(MAP_PENCIL_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw) as Array<{ x: number; y: number; svgX: number; svgY: number }>;
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });
  const [mapZoom, setMapZoom] = React.useState(1);
  const [svgLabelPositions, setSvgLabelPositions] = React.useState<Record<string, SvgLabelPosition>>({});
  const dragRef = React.useRef<{ id: string; pointerId: number; moved: boolean } | null>(null);
  // 地图 pan：translate 平移代替 overflow:auto 滚动（兼容 matrix3d 透视外框）
  const [pan, setPan] = React.useState({ x: 0, y: 0 });
  const panDragRef = React.useRef<{ pointerId: number; startX: number; startY: number; startPanX: number; startPanY: number; moved: boolean } | null>(null);
  const onMapPanDown = React.useCallback((e: React.PointerEvent) => {
    if (coordPick) return;  // 调试模式不抢拖动
    // 不立即 capture：等 move 超阈值才算拖动，否则点击（省份/节点）能正常穿透
    panDragRef.current = { pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, startPanX: pan.x, startPanY: pan.y, moved: false };
  }, [coordPick, pan.x, pan.y]);
  const onMapPanMove = React.useCallback((e: React.PointerEvent) => {
    const d = panDragRef.current;
    if (!d || d.pointerId !== e.pointerId) return;
    const dx = e.clientX - d.startX, dy = e.clientY - d.startY;
    if (!d.moved && Math.abs(dx) + Math.abs(dy) > 4) {
      d.moved = true;
      // 真拖动了才 capture，独占后续 pointer
      try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); } catch {}
    }
    if (!d.moved) return;  // 未达拖动阈值，不动地图，让 click 穿透
    // 钳制：地图始终盖满地图框，不露底图（按当前 zoom 算超出量）
    setPan(clampPanRef.current(d.startPanX + dx, d.startPanY + dy));
  }, []);
  const onMapPanUp = React.useCallback((e: React.PointerEvent) => {
    const d = panDragRef.current;
    if (!d || d.pointerId !== e.pointerId) return;
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
    panDragRef.current = null;
  }, []);
  // 玩家缩放（滚轮，以光标为中心）。map-tile transform = translate(pan) scale(userZoom)
  const [userZoom, setUserZoom] = React.useState(1);
  const ZOOM_MIN = 1, ZOOM_MAX = 3;
  const clampPan = React.useCallback((nx: number, ny: number, zoom: number) => {
    const board = mapTileRef.current, vp = viewportRef.current;
    if (!board || !vp) return { x: nx, y: ny };
    const mw = board.offsetWidth * zoom, mh = board.offsetHeight * zoom;
    // 地图比框大：钳制在 [-(超出量), 0]；地图比框小：锁定居中
    const clampAxis = (v: number, mapSize: number, frameSize: number) => {
      if (mapSize >= frameSize) return Math.min(0, Math.max(-(mapSize - frameSize), v));
      return (frameSize - mapSize) / 2;  // 居中
    };
    return {
      x: clampAxis(nx, mw, vp.clientWidth),
      y: clampAxis(ny, mh, vp.clientHeight),
    };
  }, []);
  // ref 持最新 clampPan(带当前zoom)，给 deps=[] 的 pan move 用
  const clampPanRef = React.useRef((nx: number, ny: number) => ({ x: nx, y: ny }));
  React.useEffect(() => {
    clampPanRef.current = (nx: number, ny: number) => clampPan(nx, ny, userZoom);
  }, [clampPan, userZoom]);
  const onMapWheel = React.useCallback((e: React.WheelEvent) => {
    if (coordPick) return;
    e.preventDefault();
    const vp = viewportRef.current;
    if (!vp) return;
    const rect = vp.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;  // 光标在 viewport 内坐标
    setUserZoom((z) => {
      const nz = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
      if (nz === z) return z;
      // 保持光标下的地图点不动：pan' = cursor - (cursor - pan) * nz/z
      setPan((p) => {
        const k = nz / z;
        const nx = cx - (cx - p.x) * k;
        const ny = cy - (cy - p.y) * k;
        return clampPan(nx, ny, nz);
      });
      return nz;
    });
  }, [coordPick, clampPan]);
  const pencilDragRef = React.useRef<{ pointerId: number } | null>(null);
  const terrainDragRef = React.useRef<{ pointerId: number; startSvgX: number; startSvgY: number; start: TerrainTransform } | null>(null);
  const svgCoordFromPct = React.useCallback((x: number, y: number) => ({
    svgX: +(viewBoxParts[0] + (x / 100) * viewBoxParts[2]).toFixed(2),
    svgY: +(viewBoxParts[1] + (y / 100) * viewBoxParts[3]).toFixed(2),
  }), [viewBoxParts]);
  const pickFromClient = React.useCallback((clientX: number, clientY: number, label?: string) => {
    const rect = mapTileRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const x = +(((clientX - rect.left) / rect.width) * 100).toFixed(2);
    const y = +(((clientY - rect.top) / rect.height) * 100).toFixed(2);
    const clampedX = Math.min(100, Math.max(0, x));
    const clampedY = Math.min(100, Math.max(0, y));
    const svg = svgCoordFromPct(clampedX, clampedY);
    return { x: clampedX, y: clampedY, ...svg, label };
  }, [svgCoordFromPct]);
  const saveDraggedTheater = React.useCallback((id: string, pos: { x: number; y: number }) => {
    setDraggedTheaters((current) => {
      const next = { ...current, [id]: pos };
      try {
        window.localStorage.setItem(THEATER_COORD_STORAGE_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);
  const saveTerrainTransform = React.useCallback((transform: TerrainTransform) => {
    setTerrainTransform(transform);
    try {
      window.localStorage.setItem(MAP_TERRAIN_STORAGE_KEY, JSON.stringify(transform));
    } catch {}
  }, []);
  const resizeTerrain = React.useCallback((factor: number) => {
    setTerrainTransform((current) => {
      const nextWidth = +(current.width * factor).toFixed(2);
      const nextHeight = +(current.height * factor).toFixed(2);
      const centerX = current.x + current.width / 2;
      const centerY = current.y + current.height / 2;
      const next = {
        x: +(centerX - nextWidth / 2).toFixed(2),
        y: +(centerY - nextHeight / 2).toFixed(2),
        width: nextWidth,
        height: nextHeight,
      };
      try {
        window.localStorage.setItem(MAP_TERRAIN_STORAGE_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);
  const savePencilLine = React.useCallback((line: Array<{ x: number; y: number; svgX: number; svgY: number }>) => {
    setPencilLine(line);
    try {
      window.localStorage.setItem(MAP_PENCIL_STORAGE_KEY, JSON.stringify(line));
    } catch {}
  }, []);
  const addPencilPoint = React.useCallback((point: { x: number; y: number; svgX: number; svgY: number }) => {
    setPencilLine((current) => {
      const last = current[current.length - 1];
      if (last) {
        const dx = point.svgX - last.svgX;
        const dy = point.svgY - last.svgY;
        if (Math.hypot(dx, dy) < 1.2) return current;
      }
      const next = [...current, point];
      try {
        window.localStorage.setItem(MAP_PENCIL_STORAGE_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);
  const onPickClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!coordPick || pencilMode) return;
    const next = pickFromClient(e.clientX, e.clientY);
    if (!next) return;
    setPick(next);
    console.log(`map pct: (${next.x}, ${next.y}) svg: (${next.svgX}, ${next.svgY})`);
  };
  const onPencilPointerDown = (ev: React.PointerEvent<HTMLDivElement>) => {
    if (!coordPick || !pencilMode) return;
    ev.preventDefault();
    ev.stopPropagation();
    const next = pickFromClient(ev.clientX, ev.clientY, "铅笔");
    if (!next) return;
    pencilDragRef.current = { pointerId: ev.pointerId };
    ev.currentTarget.setPointerCapture(ev.pointerId);
    const point = { x: next.x, y: next.y, svgX: next.svgX, svgY: next.svgY };
    savePencilLine([point]);
    setPick(next);
  };
  const onPencilPointerMove = (ev: React.PointerEvent<HTMLDivElement>) => {
    const drag = pencilDragRef.current;
    if (!coordPick || !pencilMode || !drag || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    const next = pickFromClient(ev.clientX, ev.clientY, "铅笔");
    if (!next) return;
    addPencilPoint({ x: next.x, y: next.y, svgX: next.svgX, svgY: next.svgY });
    setPick(next);
  };
  const onPencilPointerUp = (ev: React.PointerEvent<HTMLDivElement>) => {
    const drag = pencilDragRef.current;
    if (!coordPick || !pencilMode || !drag || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    try { ev.currentTarget.releasePointerCapture(ev.pointerId); } catch {}
    pencilDragRef.current = null;
    console.log(`pencil svg line: ${JSON.stringify(pencilLine.map((point) => [point.svgX, point.svgY]))}`);
  };
  const onTerrainPointerDown = (ev: React.PointerEvent<SVGImageElement>) => {
    if (!coordPick || !terrainMode) return;
    ev.preventDefault();
    ev.stopPropagation();
    const next = pickFromClient(ev.clientX, ev.clientY, "底图");
    if (!next) return;
    terrainDragRef.current = {
      pointerId: ev.pointerId,
      startSvgX: next.svgX,
      startSvgY: next.svgY,
      start: terrainTransform,
    };
    ev.currentTarget.setPointerCapture(ev.pointerId);
    setPick(next);
  };
  const onTerrainPointerMove = (ev: React.PointerEvent<SVGImageElement>) => {
    const drag = terrainDragRef.current;
    if (!coordPick || !terrainMode || !drag || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    const next = pickFromClient(ev.clientX, ev.clientY, "底图");
    if (!next) return;
    saveTerrainTransform({
      ...drag.start,
      x: +(drag.start.x + next.svgX - drag.startSvgX).toFixed(2),
      y: +(drag.start.y + next.svgY - drag.startSvgY).toFixed(2),
    });
    setPick(next);
  };
  const onTerrainPointerUp = (ev: React.PointerEvent<SVGImageElement>) => {
    const drag = terrainDragRef.current;
    if (!coordPick || !terrainMode || !drag || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    try { ev.currentTarget.releasePointerCapture(ev.pointerId); } catch {}
    terrainDragRef.current = null;
  };
  const onTheaterPointerDown = (node: MapNode) => (ev: React.PointerEvent<HTMLButtonElement>) => {
    if (!coordPick || node.kind !== "theater") return;
    ev.preventDefault();
    ev.stopPropagation();
    dragRef.current = { id: node.id, pointerId: ev.pointerId, moved: false };
    ev.currentTarget.setPointerCapture(ev.pointerId);
    const next = pickFromClient(ev.clientX, ev.clientY, node.label || node.id);
    if (next) {
      saveDraggedTheater(node.id, { x: next.x, y: next.y });
      setPick(next);
    }
  };
  const onTheaterPointerMove = (node: MapNode) => (ev: React.PointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!coordPick || !drag || drag.id !== node.id || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    drag.moved = true;
    const next = pickFromClient(ev.clientX, ev.clientY, node.label || node.id);
    if (!next) return;
    saveDraggedTheater(node.id, { x: next.x, y: next.y });
    setPick(next);
  };
  const onTheaterPointerUp = (node: MapNode) => (ev: React.PointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!coordPick || !drag || drag.id !== node.id || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    try { ev.currentTarget.releasePointerCapture(ev.pointerId); } catch {}
    const next = pickFromClient(ev.clientX, ev.clientY, node.label || node.id);
    if (next) {
      saveDraggedTheater(node.id, { x: next.x, y: next.y });
      setPick(next);
      console.log(`${node.id}: pct=(${next.x}, ${next.y}) svg=(${next.svgX}, ${next.svgY})`);
    }
    dragRef.current = null;
  };
  const changeMapZoom = React.useCallback((delta: number) => {
    setMapZoom((current) => Math.min(2.6, Math.max(0.8, +(current + delta).toFixed(2))));
  }, []);
  const nodeById = React.useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const regionPathItems = React.useMemo<RegionPathRenderItem[]>(
    () => REGION_PATH_GROUPS.filter((group) => !THEATER_ONLY_REGION_IDS.has(group.regionId)).map((group) => {
      const node = nodeById.get(group.regionId);
      return {
        id: group.regionId,
        name: node?.region?.name || group.regionId,
        controlledBy: MAP_DISPLAY_POWER_OVERRIDES[group.regionId] || String(node?.region?.controlled_by || "ming"),
        unrest: node?.region?.unrest || 0,
        risk: node?.risk || 0,
        labelX: node?.x ?? 50,
        labelY: node?.y ?? 50,
        paths: group.paths,
      };
    }),
    [nodeById],
  );
  const externalPathItems = React.useMemo<ExternalPathRenderItem[]>(
    () => {
      return EXTERNAL_PATH_GROUPS.filter((group) => group.paths.length > 0).map((group) => {
        const node = nodeById.get(group.id);
        return {
          ...group,
          labelX: node?.x ?? 50,
          labelY: node?.y ?? 50,
        };
      });
    },
    [nodeById],
  );

  React.useLayoutEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const next: Record<string, SvgLabelPosition> = {};
    const pathsByRegion = new Map<string, SVGGraphicsElement[]>();
    svg.querySelectorAll<SVGGraphicsElement>("path[data-region-id]").forEach((path) => {
      const id = path.getAttribute("data-region-id");
      if (!id) return;
      const current = pathsByRegion.get(id) || [];
      current.push(path);
      pathsByRegion.set(id, current);
    });
    for (const [id, paths] of pathsByRegion.entries()) {
      let minX = Number.POSITIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      for (const path of paths) {
        const box = path.getBBox();
        if (!Number.isFinite(box.x) || !Number.isFinite(box.y) || box.width <= 0 || box.height <= 0) continue;
        minX = Math.min(minX, box.x);
        minY = Math.min(minY, box.y);
        maxX = Math.max(maxX, box.x + box.width);
        maxY = Math.max(maxY, box.y + box.height);
      }
      if (Number.isFinite(minX) && Number.isFinite(minY) && Number.isFinite(maxX) && Number.isFinite(maxY)) {
        next[id] = {
          svgX: +((minX + maxX) / 2).toFixed(2),
          svgY: +((minY + maxY) / 2).toFixed(2),
        };
      }
    }
    setSvgLabelPositions(next);
  }, [regionPathItems, externalPathItems]);

  React.useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || didCenterRef.current) return;
    const board = viewport.querySelector<HTMLElement>(".map-tile");
    if (!board) return;
    didCenterRef.current = true;
    // 初始定位：河南居中（手动拖出的最佳位置，按地图尺寸比例，窗口无关）
    const INIT_FX = -0.1308, INIT_FY = -0.2895;
    setPan(clampPan(board.offsetWidth * INIT_FX, board.offsetHeight * INIT_FY, 1));
  }, [clampPan]);

  return (
    <section
      ref={viewportRef}
      className="grand-map"
      aria-label="大明地图"
      onPointerDown={onMapPanDown}
      onPointerMove={onMapPanMove}
      onPointerUp={onMapPanUp}
      onPointerCancel={onMapPanUp}
      onWheel={onMapWheel}
    >
      {coordPick ? (
        <div className="coord-toolbox">
          <button
            className={`coord-tool-button ${pencilMode ? "active" : ""}`}
            onClick={(ev) => {
              ev.stopPropagation();
              setPencilMode((current) => {
                const next = !current;
                if (next) setTerrainMode(false);
                return next;
              });
            }}
            aria-label="铅笔工具"
            title="铅笔工具"
          >
            <Pencil size={16} />
            <span>{pencilMode ? "铅笔开启" : "铅笔"}</span>
          </button>
          <button
            className="coord-tool-button"
            onClick={(ev) => {
              ev.stopPropagation();
              savePencilLine([]);
              console.log("pencil line cleared");
            }}
            aria-label="清除铅笔线"
            title="清除铅笔线"
          >
            <Eraser size={16} />
          </button>
          <button
            className={`coord-tool-button ${terrainMode ? "active" : ""}`}
            onClick={(ev) => {
              ev.stopPropagation();
              setTerrainMode((current) => {
                const next = !current;
                if (next) setPencilMode(false);
                return next;
              });
            }}
            aria-label="拖动底图"
            title="拖动底图"
          >
            <Move size={16} />
            <span>{terrainMode ? "底图开启" : "底图"}</span>
          </button>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              resizeTerrain(0.96);
            }}
            aria-label="缩小底图"
            title="缩小底图"
          >
            <ZoomOut size={16} />
          </button>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              resizeTerrain(1.04);
            }}
            aria-label="放大底图"
            title="放大底图"
          >
            <ZoomIn size={16} />
          </button>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              saveTerrainTransform(defaultTerrainTransform);
            }}
            aria-label="重置底图"
            title="重置底图"
          >
            <RotateCcw size={15} />
          </button>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              changeMapZoom(-0.15);
            }}
            aria-label="缩小地图"
            title="缩小地图"
          >
            <ZoomOut size={16} />
          </button>
          <span className="coord-zoom-readout">{Math.round(mapZoom * 100)}%</span>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              changeMapZoom(0.15);
            }}
            aria-label="放大地图"
            title="放大地图"
          >
            <ZoomIn size={16} />
          </button>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              setMapZoom(1);
            }}
            aria-label="重置缩放"
            title="重置缩放"
          >
            <RotateCcw size={15} />
          </button>
        </div>
      ) : null}
      <div
        className={`map-strip ${pencilMode ? "pencil-mode" : ""} ${terrainMode ? "terrain-mode" : ""}`}
        style={coordPick ? {
          width: `${1900 * mapZoom + 320}px`,
          height: `${(1900 * mapZoom * 206) / 276 + 240}px`,
        } : undefined}
        onClick={onPickClick}
        onPointerDown={onPencilPointerDown}
        onPointerMove={onPencilPointerMove}
        onPointerUp={onPencilPointerUp}
        onPointerCancel={onPencilPointerUp}
      >
        <div
          className="map-tile"
          ref={mapTileRef}
          style={coordPick
            ? { width: `${1900 * mapZoom}px` }
            : { transform: `translate(${pan.x}px, ${pan.y}px) scale(${userZoom})`, transformOrigin: "0 0" }}
        >
            <svg
              ref={svgRef}
              className="province-map-layer"
              viewBox={MAP_VIEW_BOX}
              preserveAspectRatio="xMinYMin meet"
            >
              <image
                className={`map-terrain-image ${coordPick && terrainMode ? "draggable" : ""}`}
                href="/ming-1627-terrain-map.png"
                x={terrainTransform.x}
                y={terrainTransform.y}
                width={terrainTransform.width}
                height={terrainTransform.height}
                preserveAspectRatio="xMidYMid slice"
                onPointerDown={onTerrainPointerDown}
                onPointerMove={onTerrainPointerMove}
                onPointerUp={onTerrainPointerUp}
                onPointerCancel={onTerrainPointerUp}
              />
              {externalPathItems.map((group) => {
                const selected = selectedId === group.id;
                const fill = EXTERNAL_MAP_COLOR;
                return (
                  <g
                    key={`${group.id}:external-paths`}
                    className={`province-external power-${group.powerId} ${selected ? "selected" : ""}`}
                    data-external-id={group.id}
                    style={{ "--province-fill": fill } as React.CSSProperties}
                  >
                    {group.paths.map((path) => (
                      <path
                        key={`${group.id}:${path.id}`}
                        data-map-path-id={path.id}
                        data-region-id={group.id}
                        fill={fill}
                        fillOpacity={EXTERNAL_MAP_OPACITY}
                        d={path.d}
                        onClick={(ev) => {
                          ev.stopPropagation();
                          ev.currentTarget.blur();
                          onSelect(group.id);
                        }}
                        role="button"
                        aria-label={`查看${group.name}`}
                        onKeyDown={(ev) => {
                          if (ev.key === "Enter" || ev.key === " ") {
                            ev.preventDefault();
                            onSelect(group.id);
                          }
                        }}
                      >
                        <title>{group.name}</title>
                      </path>
                    ))}
                  </g>
                );
              })}
              {regionPathItems.map((region) => {
                const selected = selectedId === region.id;
                const fill = getRegionMapColor(region);
                return (
                  <g
                    key={`${region.id}:paths`}
                    data-region-id={region.id}
                    className={`province-region power-${region.controlledBy} ${selected ? "selected" : ""} ${region.controlledBy === "ming" && region.unrest > UNREST_DANGER_THRESHOLD ? "danger" : ""}`}
                    style={{ "--province-fill": fill } as React.CSSProperties}
                  >
                    {region.paths.map((path) => (
                      <path
                        key={path.id}
                        data-map-path-id={path.id}
                        data-region-id={region.id}
                        fill={fill}
                        fillOpacity={getRegionMapOpacity(region)}
                        d={path.d}
                        onClick={(ev) => {
                          ev.stopPropagation();
                          ev.currentTarget.blur();
                          onSelect(region.id);
                        }}
                        role="button"
                        aria-label={`查看${region.name}`}
                        onKeyDown={(ev) => {
                          if (ev.key === "Enter" || ev.key === " ") {
                            ev.preventDefault();
                            onSelect(region.id);
                          }
                        }}
                      >
                        <title>{region.name}</title>
                      </path>
                    ))}
                  </g>
                );
              })}
              {pencilLine.length > 1 ? (
                <polyline
                  className="coord-pencil-line"
                  points={pencilLine.map((point) => `${point.svgX},${point.svgY}`).join(" ")}
                />
              ) : null}
              <g className="map-label-layer" aria-hidden="true">
                {externalPathItems.map((group) => {
                  const pos = svgLabelPositions[group.id] || svgCoordFromPct(group.labelX, group.labelY);
                  return (
                    <text
                      key={`${group.id}:label`}
                      className="map-region-label external"
                      x={pos.svgX}
                      y={pos.svgY}
                    >
                      {group.name.split(" / ")[0]}
                    </text>
                  );
                })}
                {regionPathItems.map((region) => {
                  const pos = svgLabelPositions[region.id] || svgCoordFromPct(region.labelX, region.labelY);
                  return (
                    <text
                      key={`${region.id}:label`}
                      className="map-region-label"
                      x={pos.svgX}
                      y={pos.svgY}
                    >
                      {region.name.split(" / ")[0]}
                    </text>
                  );
                })}
              </g>
            </svg>
            {nodes.filter((node) => node.kind === "theater").map((node) => {
              const selected = selectedId === node.id;
              const danger = node.risk > 175;
              const override = draggedTheaters[node.id];
              const nodeX = override?.x ?? node.x;
              const nodeY = override?.y ?? node.y;
              return (
                <button
                  key={node.id}
                  className={`map-node ${node.kind} ${coordPick ? "draggable" : ""} ${selected ? "selected" : ""} ${danger ? "danger" : ""}`}
                  style={{ left: `${nodeX}%`, top: `${nodeY}%` }}
                  data-node-id={node.id}
                  onPointerDown={(ev) => {
                    if (!coordPick) ev.stopPropagation();  // 防止触发地图 pan
                    onTheaterPointerDown(node)(ev);
                  }}
                  onPointerMove={onTheaterPointerMove(node)}
                  onPointerUp={onTheaterPointerUp(node)}
                  onPointerCancel={onTheaterPointerUp(node)}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    if (coordPick) return;
                    onSelect(node.id);
                  }}
                  aria-label={`查看${node.region?.name || node.label}`}
                  tabIndex={0}
                >
                  {node.kind === "theater" ? <Shield size={16} /> : <MapPinned size={15} />}
                  <span>{node.region?.name.split(" / ")[0] || node.label}</span>
                </button>
              );
            })}
        </div>
      </div>
      {coordPick && pick ? (
        <div className="coord-pick-readout">
          {pick.label ? `${pick.label} ` : ""}pct: ({pick.x}, {pick.y}) &nbsp; svg: ({pick.svgX}, {pick.svgY})
        </div>
      ) : null}
    </section>
  );
}

export function NodeIntel({ node }: { node: MapNode }) {
  const region = node.region;
  const power = node.power;
  if (node.kind === "external") {
    return (
      <>
        <div className="panel-title">
          <MapPinned size={14} />
          <span>{region?.name || node.label}</span>
        </div>
        <table className="intel-table">
          <tbody>
            <tr><th>归属</th><td colSpan={3}>{labelPower(region?.controlled_by || power?.id || "")}</td></tr>
          </tbody>
        </table>
        <div className="empty-note">非大明辖治，详情不可见。</div>
      </>
    );
  }
  return (
    <>
      <div className="panel-title">
        {node.kind === "theater" ? <Shield size={14} /> : <MapPinned size={14} />}
        <span>{region?.name || node.label}</span>
      </div>
      {region ? (
        <table className="intel-table">
          <tbody>
            <tr><th>人口</th><td>{region.population}万</td><th>田亩</th><td>{region.registered_land}万亩</td></tr>
            <tr><th>民心</th><td>{region.public_support}</td><th>动乱</th><td>{region.unrest}</td></tr>
            <tr><th>粮食</th><td>{region.grain_security}</td><th>月税</th><td>{monthlyAmount(region.tax_per_turn)}万/月</td></tr>
            <tr><th>归属</th><td>{labelPower(region.controlled_by || "ming")}</td><th>类型</th><td>{region.kind}</td></tr>
            <tr><th>天灾</th><td colSpan={3}>{region.natural_disaster}</td></tr>
            <tr><th>人祸</th><td colSpan={3}>{region.human_disaster}</td></tr>
            <tr><th>状况</th><td colSpan={3}>{region.status}</td></tr>
          </tbody>
        </table>
      ) : null}
      {power && power.id !== "ming" ? (
        <>
          <div className="garrison-title">势力归属</div>
          <table className="intel-table">
            <tbody>
              <tr><th>势力</th><td>{power.name}</td><th>首领</th><td>{power.leader}</td></tr>
              <tr><th>立场</th><td>{power.stance}</td><th>类型</th><td>{power.kind}</td></tr>
              <tr><th>军力</th><td>{power.military_strength}</td><th>凝聚</th><td>{power.cohesion}</td></tr>
              <tr><th>影响</th><td>{power.leverage}</td><th>补给</th><td>{power.supply}</td></tr>
              <tr><th>诉求</th><td colSpan={3}>{power.agenda}</td></tr>
              <tr><th>近况</th><td colSpan={3}>{power.last_action}</td></tr>
            </tbody>
          </table>
        </>
      ) : null}
      <div className="garrison-title">驻军</div>
      {node.armies.length ? (
        <table className="intel-table">
          <thead>
            <tr><th>番号</th><th>兵种</th><th>兵</th><th>饷</th><th>士气</th><th>欠饷</th></tr>
          </thead>
          <tbody>
            {node.armies.map((army) => {
              const maint = army.maintenance_per_turn || 0;
              const arr = army.arrears || 0;
              const months = maint > 0 && arr > 0 ? (arr / maint) : 0;
              const arrText = arr > 0
                ? (months > 0 ? `${arr}万两（≈${months.toFixed(1)}月）` : `${arr}万两`)
                : '—';
              return (
                <tr key={army.id}>
                  <td>{army.name}</td>
                  <td>{army.troop_type}</td>
                  <td>{army.manpower}</td>
                  <td>{monthlyAmount(maint)}</td>
                  <td>{army.morale}</td>
                  <td>{arrText}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : <div className="empty-note">本地未记录常驻军。</div>}
      {region ? (
        <>
          <div className="garrison-title">建筑</div>
          {node.buildings && node.buildings.length ? (
            <table className="intel-table">
              <thead>
                <tr><th>名称</th><th>类别</th><th>等级</th><th>完好</th><th>维护</th><th>产出</th></tr>
              </thead>
              <tbody>
                {node.buildings.map((b) => (
                  <tr key={b.id}>
                    <td>{b.name}</td>
                    <td>{b.category}</td>
                    <td>{b.level}</td>
                    <td>{b.condition}</td>
                    <td>{b.maintenance}万/月</td>
                    <td>{b.output_metric ? `${b.output_metric}+${b.output_amount}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="empty-note">本地未记录建筑。</div>}
        </>
      ) : null}
    </>
  );
}

export function Info({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div className={`info-cell ${tone || ""}`}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}
