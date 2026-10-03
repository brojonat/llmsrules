// d3 charts as Datastar Rocket web components.
//
// The server stays in charge: it renders each chart as a bare custom element
// whose attributes carry the data, e.g.
//
//   <chart-bars id="year-bars" series='[["2019",14012],...]' highlight="2026">
//
// and later morphs change those attributes. Rocket decodes each attribute
// through its prop codec and calls observeProps, and d3 redraws with a
// transition. Components render into an open shadow root, so the page morph
// never touches what d3 drew. Nothing here holds application state; chart
// data never goes into signals.

import { rocket } from 'datastar'
import * as d3 from 'd3'
import { feature, mesh } from 'topojson-client'

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
const duration = () => (reduceMotion.matches ? 0 : 300)

// 1.6M, 95.9K, 950, 3.1. Matches the server's compact() used in tiles.
const compact = (v) => {
  const a = Math.abs(v)
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (a >= 1e4) return `${(v / 1e3).toFixed(1)}K`
  if (a >= 100 || Number.isInteger(v)) return d3.format(',.0f')(v)
  if (a >= 1) return v.toFixed(1)
  return d3.format('.2~g')(v)
}
const commas = d3.format(',')

// Shared chart styling. Colors come from the page's CSS custom properties,
// which inherit through the shadow boundary, so light/dark follow the page.
const STYLE = `
  :host { display: block; position: relative; }
  svg { display: block; width: 100%; overflow: visible; }
  text { font: 11px system-ui, sans-serif; fill: var(--ink-muted); }
  .grid line { stroke: var(--grid); }
  .base { stroke: var(--baseline); }
  .bar { fill: var(--series-1); }
  .bar.hl { fill: color-mix(in srgb, var(--series-1) 25%, transparent); stroke: var(--series-1); stroke-width: 1.5; }
  .bar.dim { opacity: .45; }
  .bar.off { opacity: .28; }
  .drag-band { fill: color-mix(in srgb, var(--series-1) 18%, transparent); stroke: var(--series-1); stroke-dasharray: 3 2; pointer-events: none; }
  .line { fill: none; stroke: var(--ink-muted); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .now { fill: var(--series-1); }
  .cross { stroke: var(--ink-muted); stroke-dasharray: 2 2; }
  .hit { fill: transparent; cursor: default; }
  .state { stroke: var(--surface); stroke-width: 1; cursor: pointer; outline: none; }
  .state.hover, .state:focus-visible { stroke: var(--ink); stroke-width: 1.5; }
  .state.selected { stroke: var(--ink); stroke-width: 2.5; }
  .legend text { font-size: 11px; }
  .label { font-size: 14px; fill: var(--ink); }
  .value { font-size: 13px; fill: var(--ink-muted); font-variant-numeric: tabular-nums; }
  .tip { position: absolute; pointer-events: none; white-space: nowrap; z-index: 1;
         font: 13px/1.3 system-ui, sans-serif; padding: .3rem .5rem; border-radius: 6px;
         color: var(--ink); background: var(--surface);
         border: 1px solid color-mix(in srgb, var(--ink) 20%, transparent);
         box-shadow: 0 2px 8px rgb(0 0 0 / .15); transform: translate(-50%, calc(-100% - 8px)); }
  .tip[hidden] { display: none; }
`

// Wires a component up: a shadow root with an <svg> and a tooltip, a redraw
// on data props and on resize. `draw(ctx)` owns everything inside the svg.
const chart = (tag, { props, draw }) =>
  rocket(tag, {
    mode: 'open',
    props,
    // d3 owns the DOM after the first render; prop changes redraw, not re-render.
    renderOnPropChange: false,
    render: ({ html }) => html`<style>${STYLE}</style><svg></svg><div class="tip" hidden></div>`,
    onFirstRender: ({ host, props, observeProps, cleanup, emit }) => {
      const root = host.shadowRoot
      const svg = d3.select(root.querySelector('svg'))
      const tip = root.querySelector('.tip')
      const tooltip = {
        show(x, y, text) {
          tip.textContent = text
          tip.style.left = `${x}px`
          tip.style.top = `${y}px`
          tip.hidden = false
        },
        hide() {
          tip.hidden = true
        },
      }
      let width = 0
      const redraw = (animate) => {
        width = host.clientWidth || width
        if (width) draw({ svg, props, width, tooltip, emit, host, t: animate ? duration() : 0 })
      }
      observeProps(() => redraw(true))
      const ro = new ResizeObserver(() => {
        if (host.clientWidth !== width) redraw(false)
      })
      ro.observe(host)
      cleanup(() => ro.disconnect())
      redraw(false)
    },
  })

// A path for a bar with rounded data end (top) and a square foot on the baseline.
const barPath = (x, y, w, h, r) => {
  r = Math.max(0, Math.min(r, w / 2, h))
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

// Vertical bars: one series over an ordinal axis (e.g. tickets per year).
// `highlight` names one category drawn hollow (a partial period).
chart('chart-bars', {
  props: ({ json, string, number, bool }) => ({
    series: json.default(() => []),
    highlight: string.default(''),
    highlightNote: string.default(''),
    label: string.default('bar chart'),
    unit: string.default(''),
    height: number.default(220),
    yMax: number.default(0), // > 0: fixed y domain (faceted charts share one scale)
    // Selection: drag across bars to pick a range (emits chart-range {from, to}),
    // click one to toggle it (chart-toggle {value}). `selected` comes back from
    // the server; this component holds no selection state of its own.
    selectable: bool.default(false),
    selected: json.default(() => []),
  }),
  draw: ({ svg, props, width, tooltip, emit, t }) => {
    // v null = no data for that category: an empty slot, not a zero bar.
    const data = props.series.map(([k, v]) => ({ k: String(k), v: v == null ? null : +v }))
    const chosen = new Set((props.selected || []).map(String))
    const h = props.height
    const m = { top: 12, right: 8, bottom: 24, left: 44 }
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h)
      .attr('role', 'img').attr('aria-label', props.label)

    const x = d3.scaleBand().domain(data.map((d) => d.k)).range([m.left, width - m.right]).paddingInner(0)
    const top = props.yMax || d3.max(data, (d) => d.v ?? 0) || 1
    const small = h < 150
    const y = d3.scaleLinear().domain([0, top]).nice(small ? 2 : 4).range([h - m.bottom, m.top])
    const gap = 2 // 2px surface gap between bars
    const bw = Math.max(1, x.bandwidth() - gap)

    svg.selectAll('g.grid').data([0]).join('g').attr('class', 'grid')
      .transition().duration(t)
      .call(d3.axisLeft(y).ticks(small ? 2 : 4).tickSize(-(width - m.left - m.right)).tickFormat(compact))
      .attr('transform', `translate(${m.left},0)`)
      .call((g) => g.select('.domain').remove())
      .call((g) => g.selectAll('text').attr('x', -6))

    // Every Nth label, plus the last one; drop a regular label that would
    // crowd the last (2025 and 2026 printing on top of each other).
    const every = Math.max(1, Math.round(data.length / Math.max(2, Math.floor(width / 90))))
    const last = data.length - 1
    const ticks = data.filter((_, i) => i === last || (i % every === 0 && last - i >= Math.max(2, every / 2)))
    svg.selectAll('g.x').data([0]).join('g').attr('class', 'x')
      .attr('transform', `translate(0,${h - m.bottom})`)
      .call(d3.axisBottom(x).tickSize(0).tickPadding(8).tickValues(ticks.map((d) => d.k)))
      .call((g) => g.select('.domain').remove())

    svg.selectAll('path.bar').data(data, (d) => d.k)
      .join(
        (enter) => enter.append('path').attr('d', (d) => barPath(x(d.k) + gap / 2, y(0), bw, 0, 4)),
        (update) => update,
        (exit) => exit.transition().duration(t).attr('opacity', 0).remove(),
      )
      .attr('class', (d) => (d.k === props.highlight ? 'bar hl' : 'bar'))
      .classed('off', (d) => chosen.size > 0 && !chosen.has(d.k))
      .transition().duration(t)
      .attr('d', (d) => barPath(x(d.k) + gap / 2, y(d.v ?? 0), bw, y(0) - y(d.v ?? 0), 4))

    svg.selectAll('line.base').data([0]).join('line').attr('class', 'base')
      .attr('x1', m.left).attr('x2', width - m.right).attr('y1', y(0)).attr('y2', y(0))

    if (props.selectable) {
      // Keep what the pointer handlers need on the node; they're bound once.
      const node = svg.node()
      node.__sel = { x, data, emit, top: m.top, height: h - m.top - m.bottom }
      if (!node.__selBound) {
        node.__selBound = true
        const band = svg.append('rect').attr('class', 'drag-band').attr('visibility', 'hidden')
        let start = null
        const keyAt = (px) => {
          const { x: sx, data: sd } = node.__sel
          return sd.find((d) => px >= sx(d.k) && px < sx(d.k) + sx.bandwidth())?.k
        }
        svg.on('pointerdown', (evt) => {
          if (evt.button !== 0) return
          start = d3.pointer(evt, node)[0]
          node.setPointerCapture(evt.pointerId)
        })
        svg.on('pointermove.drag', (evt) => {
          if (start == null) return
          const px = d3.pointer(evt, node)[0]
          if (Math.abs(px - start) < 4) return
          tooltip.hide()
          const { top: bt, height: bh } = node.__sel
          band.attr('visibility', 'visible').attr('x', Math.min(px, start)).attr('width', Math.abs(px - start))
            .attr('y', bt).attr('height', bh)
        })
        svg.on('pointerup', (evt) => {
          if (start == null) return
          const px = d3.pointer(evt, node)[0]
          const { x: sx, data: sd, emit: send } = node.__sel
          band.attr('visibility', 'hidden')
          if (Math.abs(px - start) < 4) {
            const k = keyAt(px)
            if (k != null) send('chart-toggle', { value: k })
          } else {
            const [lo, hi] = [Math.min(px, start), Math.max(px, start)]
            const keys = sd.filter((d) => {
              const c = sx(d.k) + sx.bandwidth() / 2
              return c >= lo && c <= hi
            }).map((d) => d.k)
            if (keys.length) send('chart-range', { from: keys[0], to: keys[keys.length - 1] })
          }
          start = null
        })
      }
      svg.style('cursor', 'crosshair').style('touch-action', 'none')
    }

    // Hit targets span the full column, larger than the mark.
    svg.selectAll('rect.hit').data(data, (d) => d.k).join('rect').attr('class', 'hit')
      .attr('x', (d) => x(d.k)).attr('width', x.bandwidth())
      .attr('y', m.top).attr('height', h - m.top - m.bottom)
      .on('pointerenter pointermove', (evt, d) => {
        svg.selectAll('path.bar').classed('dim', (b) => b.k !== d.k)
        const note = d.k === props.highlight && props.highlightNote ? ` (${props.highlightNote})` : ''
        const value = d.v == null ? 'no data' : `${commas(d.v)}${props.unit}`
        tooltip.show(x(d.k) + x.bandwidth() / 2, y(d.v ?? 0), `${d.k}: ${value}${note}`)
      })
      .on('pointerleave', () => {
        svg.selectAll('path.bar').classed('dim', false)
        tooltip.hide()
      })
  },
})

// Horizontal bars: a ranked list with the label above each bar and the value
// at the right. Keyed by label, so a re-rank slides rows to their new place.
chart('chart-hbars', {
  props: ({ json, string, number }) => ({
    series: json.default(() => []),
    label: string.default('ranked bar chart'),
    unit: string.default(''),
    yMax: number.default(0), // > 0: fixed value domain (faceted charts share one scale)
  }),
  // Two layouts. Up to 20 rows: label above each bar (roomy). Longer rankings
  // (all 56 states, say): compact rows, labels in a left column, values at the
  // right, so 56 rows take ~1,000px instead of 2,000.
  draw: ({ svg, props, width, tooltip, t }) => {
    const data = props.series.map(([k, v]) => ({ k: String(k), v: +v }))
    const compact = data.length > 20
    const row = compact ? 18 : 36
    const labelW = compact ? Math.min(width * 0.35, 8 + 7 * d3.max(data, (d) => d.k.length) || 0) : 0
    const valueW = compact ? 64 : 0
    const barX = labelW
    const barMax = width - labelW - valueW - 4
    const h = Math.max(row, data.length * row)
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h)
      .attr('role', 'img').attr('aria-label', props.label)
    const x = d3.scaleLinear().domain([0, props.yMax || d3.max(data, (d) => d.v) || 1]).range([0, compact ? barMax : width])
    const [top, bottom, textY] = compact ? [4, 14, 13] : [20, 28, 14]

    const rows = svg.selectAll('g.row').data(data, (d) => d.k)
      .join(
        (enter) => {
          const g = enter.append('g').attr('class', 'row')
            .attr('transform', (_, i) => `translate(0,${i * row})`).attr('opacity', 0)
          g.append('text').attr('class', 'label')
          g.append('text').attr('class', 'value').attr('text-anchor', 'end')
          g.append('path').attr('class', 'bar')
          g.append('rect').attr('class', 'hit')
          return g
        },
        (update) => update,
        (exit) => exit.transition().duration(t).attr('opacity', 0).remove(),
      )
    rows.transition().duration(t).attr('opacity', 1).attr('transform', (_, i) => `translate(0,${i * row})`)
    rows.select('.label').attr('y', textY).style('font-size', compact ? '12px' : null).text((d) => d.k)
    rows.select('.value').attr('x', width).attr('y', textY).style('font-size', compact ? '11px' : null)
      .text((d) => `${commas(d.v)}${compact ? '' : props.unit}`)
    // Horizontal bar: square foot at the axis, rounded data end on the right.
    rows.select('.bar').transition().duration(t)
      .attr('d', (d) => {
        const w = Math.max(1, x(d.v))
        const r = Math.min(4, w, (bottom - top) / 2)
        return `M${barX},${top}H${barX + w - r}Q${barX + w},${top} ${barX + w},${top + r}` +
               `V${bottom - r}Q${barX + w},${bottom} ${barX + w - r},${bottom}H${barX}Z`
      })
    rows.select('.hit').attr('width', width).attr('height', row)
      .on('pointerenter pointermove', (evt, d) => {
        rows.select('.bar').classed('dim', (b) => b.k !== d.k)
        tooltip.show(Math.min(Math.max(barX + x(d.v), 60), width - 60), data.indexOf(d) * row + top,
          `${d.k}: ${commas(d.v)}${props.unit}`)
      })
      .on('pointerleave', () => {
        rows.select('.bar').classed('dim', false)
        tooltip.hide()
      })
  },
})

// Sparkline: a single trend with the latest point in the accent color, and a
// crosshair + tooltip on hover.
chart('chart-sparkline', {
  props: ({ json, string, number }) => ({
    series: json.default(() => []),
    unit: string.default(''),
    label: string.default('trend'),
    step: number.default(1), // seconds between samples
    height: number.default(40),
  }),
  draw: ({ svg, props, width, tooltip }) => {
    const data = props.series.map(Number)
    const h = props.height
    const pad = 4
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h)
      .attr('role', 'img')
      .attr('aria-label', data.length > 1
        ? `${props.label}: last ${data.length} samples, low ${compact(d3.min(data))} high ${compact(d3.max(data))}`
        : `${props.label}: not enough samples yet`)
    if (data.length < 2) {
      svg.selectAll('*').remove()
      return
    }
    const x = d3.scaleLinear().domain([0, data.length - 1]).range([pad, width - pad])
    let [lo, hi] = d3.extent(data)
    if (lo === hi) hi = lo + 1
    const y = d3.scaleLinear().domain([lo, hi]).range([h - pad, pad])

    svg.selectAll('line.base').data([0]).join('line').attr('class', 'base')
      .attr('x1', pad).attr('x2', width - pad).attr('y1', h - pad).attr('y2', h - pad)
    // The window slides every sample; redraw in place rather than tween.
    svg.selectAll('path.line').data([data]).join('path').attr('class', 'line')
      .attr('d', d3.line().x((_, i) => x(i)).y((d) => y(d)))
    svg.selectAll('circle.now').data([data.at(-1)]).join('circle').attr('class', 'now')
      .attr('r', 4).attr('cx', x(data.length - 1)).attr('cy', (d) => y(d))
    const cross = svg.selectAll('line.cross').data([0]).join('line').attr('class', 'cross')
      .attr('y1', pad).attr('y2', h - pad).attr('visibility', 'hidden')
    svg.selectAll('rect.hit').data([0]).join('rect').attr('class', 'hit')
      .attr('x', 0).attr('y', 0).attr('width', width).attr('height', h)
      .on('pointermove', (evt) => {
        const [px] = d3.pointer(evt)
        const i = Math.max(0, Math.min(data.length - 1, Math.round(x.invert(px))))
        cross.attr('x1', x(i)).attr('x2', x(i)).attr('visibility', 'visible')
        const ago = data.length - 1 - i
        tooltip.show(x(i), y(data[i]), `${compact(data[i])}${props.unit}${ago ? ` · ${compact(ago * props.step)}s ago` : ' · now'}`)
      })
      .on('pointerleave', () => {
        cross.attr('visibility', 'hidden')
        tooltip.hide()
      })
  },
})

// ---------------------------------------------------------------------------
// Choropleth of US states.
//
// series: [[fips, usps, name, count, value|null], ...]. `value` is what gets
// colored (a count, a rate, an index or an average); null means "too few to
// rate". `noun` names what's counted ("ticket"), for tooltips and the legend.
// metric "index" uses a diverging scale around 1; everything else a
// sequential one-hue ramp in quantile bins, so one huge state (CA, TX) does
// not flatten everyone else into the lightest bin.
//
// Clicking (or Enter on) a state emits `chart-state` with detail {state} (a
// USPS code). The page turns that into a toggle command; the selection comes
// back from the server as the `selected` attribute.
// ---------------------------------------------------------------------------

// Pre-projected (Albers USA, AK/HI inset) geometry, 975×610 units.
const ATLAS = 'https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-albers-10m.json'
let atlas = null
const atlasReady = fetch(ATLAS)
  .then((r) => r.json())
  .then((topo) => {
    atlas = {
      states: feature(topo, topo.objects.states).features,
      nation: feature(topo, topo.objects.nation),
      borders: mesh(topo, topo.objects.states, (a, b) => a !== b),
    }
  })

const BINS = 7
// Index bins are symmetric in log space around 1 (the national mix).
const INDEX_THRESHOLDS = [1 / 2, 2 / 3, 5 / 6, 6 / 5, 3 / 2, 2]
const fmtIndex = (v) => (v >= 10 ? d3.format('.0f')(v) : d3.format('.2~f')(v)) + '×'

const tokens = (host) => {
  const cs = getComputedStyle(host)
  const v = (name) => cs.getPropertyValue(name).trim()
  return { lo: v('--seq-lo'), hi: v('--seq-hi'), neg: v('--div-lo'), pos: v('--div-hi'), mid: v('--neutral'),
           surface: v('--surface'), ink: v('--ink') }
}

const colorScale = (metric, values, c) => {
  if (metric === 'index') {
    const arm = (to) => d3.interpolateLab(c.mid, to)
    const colors = [arm(c.neg)(1), arm(c.neg)(0.66), arm(c.neg)(0.33), c.mid, arm(c.pos)(0.33), arm(c.pos)(0.66), arm(c.pos)(1)]
    const scale = d3.scaleThreshold().domain(INDEX_THRESHOLDS).range(colors)
    const edges = [null, ...INDEX_THRESHOLDS, null]
    const legend = colors.map((color, i) => ({
      color,
      text: edges[i] == null ? `< ${fmtIndex(edges[i + 1])}` : edges[i + 1] == null ? `≥ ${fmtIndex(edges[i])}`
        : `${fmtIndex(edges[i])}–${fmtIndex(edges[i + 1])}`,
    }))
    return { scale, legend, fmt: fmtIndex }
  }
  const ramp = d3.interpolateLab(c.lo, c.hi)
  const colors = d3.range(BINS).map((i) => ramp((i + 0.5) / BINS))
  const scale = d3.scaleQuantile().domain(values).range(colors)
  const q = [d3.min(values), ...scale.quantiles(), d3.max(values)]
  const fmt = metric === 'count' ? compact : (v) => (v >= 100 ? d3.format(',.0f')(v) : d3.format('.3~r')(v))
  const legend = colors.map((color, i) => ({ color, text: `${fmt(q[i])}–${fmt(q[i + 1])}` }))
  return { scale, legend, fmt }
}

chart('chart-map', {
  props: ({ json, string, number }) => ({
    series: json.default(() => []),
    metric: string.default('count'),
    noun: string.default('ticket'),
    unit: string.default(''),
    selected: string.default(''),
    minCount: number.default(20),
    label: string.default('map of US states'),
  }),
  draw: function draw(ctx) {
    if (!atlas) {
      atlasReady.then(() => draw(ctx))
      return
    }
    const { svg, props, width, tooltip, emit, host, t } = ctx
    const c = tokens(host)
    const rows = new Map(props.series.map(([fips, code, name, n, v]) => [fips, { fips, code, name, n, v }]))
    const values = [...rows.values()].map((d) => d.v).filter((v) => v != null)
    const { scale, legend, fmt } = colorScale(props.metric, values.length ? values : [0], c)

    const mapH = Math.round((width * 610) / 975)
    const legendH = 44
    const h = mapH + legendH
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h).attr('role', 'img').attr('aria-label', props.label)
    const path = d3.geoPath(d3.geoIdentity().fitSize([width, mapH], atlas.nation))

    // "Too few to rate": a hatch, so it never reads as a low value.
    const defs = svg.selectAll('defs').data([0]).join('defs')
    defs.selectAll('pattern#few').data([0]).join((e) => {
      const p = e.append('pattern').attr('id', 'few').attr('patternUnits', 'userSpaceOnUse')
        .attr('width', 6).attr('height', 6).attr('patternTransform', 'rotate(45)')
      p.append('rect').attr('width', 6).attr('height', 6)
      p.append('line').attr('x1', 0).attr('y1', 0).attr('x2', 0).attr('y2', 6).attr('stroke-width', 2)
      return p
    })
    defs.select('pattern#few rect').attr('fill', c.surface)
    defs.select('pattern#few line').attr('stroke', c.mid)

    const fill = (f) => {
      const d = rows.get(f.id)
      if (!d || d.v == null) return 'url(#few)'
      return scale(d.v)
    }
    const describe = (d) => {
      if (!d) return 'no data'
      const n = `${commas(d.n)} ${props.noun}${d.n === 1 ? '' : 's'}`
      if (props.metric === 'count') return `${d.name}: ${n}`
      if (d.v == null) return `${d.name}: ${n} (too few to rate)`
      return `${d.name}: ${fmt(d.v)}${props.metric === 'index' ? '' : props.unit} · ${n}`
    }
    // `selected` is a comma list of USPS codes; clicking toggles one (the
    // server decides, and sends the new list back).
    const chosen = new Set(props.selected.split(',').filter(Boolean))
    const select = (f) => {
      const d = rows.get(f.id)
      // An object, not a bare string: Rocket's emit(type, 'CA') would treat
      // 'CA' as a second event *name* and send no detail at all.
      if (d) emit('chart-state', { state: d.code })
    }

    const g = svg.selectAll('g.states').data([0]).join('g').attr('class', 'states')
    g.selectAll('path.state').data(atlas.states, (f) => f.id)
      .join((e) => e.append('path').attr('class', 'state').attr('tabindex', 0).attr('role', 'button')
        .attr('fill', fill))
      .attr('d', path)
      .attr('aria-label', (f) => describe(rows.get(f.id)))
      .attr('aria-pressed', (f) => String(chosen.has(rows.get(f.id)?.code)))
      .on('pointerenter pointermove', (evt, f) => {
        const [x, y] = d3.pointer(evt, svg.node())
        tooltip.show(x, y, describe(rows.get(f.id)))
        d3.select(evt.currentTarget).raise().classed('hover', true)
      })
      .on('pointerleave', (evt) => {
        tooltip.hide()
        d3.select(evt.currentTarget).classed('hover', false)
        svg.selectAll('path.state.selected').raise()
      })
      .on('click', (evt, f) => select(f))
      .on('keydown', (evt, f) => {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault()
          select(f)
        }
      })
      .classed('selected', (f) => chosen.has(rows.get(f.id)?.code))
      .transition().duration(t).attr('fill', fill)
    svg.selectAll('path.state.selected').raise()

    // Legend: one swatch per bin, plus the hatch when some states are unrated.
    const items = [...legend]
    if (props.metric !== 'count' && values.length < rows.size) {
      items.push({ color: 'url(#few)', text: `< ${props.minCount} ${props.noun}s` })
    }
    const sw = Math.min(90, (width - 8) / items.length)
    const lg = svg.selectAll('g.legend').data([0]).join('g').attr('class', 'legend')
      .attr('transform', `translate(${Math.max(0, (width - sw * items.length) / 2)},${mapH + 10})`)
    const it = lg.selectAll('g.item').data(items).join((e) => {
      const gi = e.append('g').attr('class', 'item')
      gi.append('rect').attr('height', 10).attr('rx', 2)
      gi.append('text').attr('y', 26).attr('text-anchor', 'middle')
      return gi
    })
    it.attr('transform', (_, i) => `translate(${i * sw},0)`)
    it.select('rect').attr('width', sw - 2).attr('fill', (d) => d.color)
    it.select('text').attr('x', (sw - 2) / 2).text((d) => d.text)
  },
})

// ---------------------------------------------------------------------------
// Lines: 1–4 series over a shared x (years, months, or categories).
//
// series: [{name, points: [[x, y], ...]}, ...]. Numeric x (years) gets a
// linear scale; anything else is ordinal in first-seen order. Categorical
// colors in fixed order (--cat-1..4, validated), a legend for 2+ series, and
// direct labels at each line's end so identity never rests on color alone.
// Hover: a crosshair and one tooltip listing every series at that x.
// `highlight` marks one x as partial (the current year), dashing the last
// segment into it.
// ---------------------------------------------------------------------------
chart('chart-lines', {
  props: ({ json, string, number, bool }) => ({
    series: json.default(() => []),
    unit: string.default(''),
    highlight: string.default(''),
    label: string.default('line chart'),
    height: number.default(200),
    yMax: number.default(0), // > 0: fixed y domain (faceted charts share one scale)
    xMin: number.default(0), // both set: fixed numeric x domain, so facets line up
    xMax: number.default(0),
    legend: bool.default(true), // faceted charts draw one shared legend instead
  }),
  draw: ({ svg, props, width, tooltip, t }) => {
    // `c` (optional) is the series' color slot, fixed across facets so a series
    // keeps its color even in a panel where others are missing.
    const series = props.series.slice(0, 4).map((s, i) => ({
      name: String(s.name ?? ''),
      color: `var(--cat-${(s.c ?? i) + 1})`,
      points: (s.points || []).map(([x, y]) => ({ x, y: y == null ? null : +y })),
    }))
    const multi = series.length > 1 || series.some((s) => s.name)
    const showLegend = multi && props.legend
    const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))]
    const numeric = xs.every((x) => typeof x === 'number')
    if (numeric) xs.sort((a, b) => a - b)
    const legendH = showLegend ? 22 : 0
    const h = props.height + legendH
    const small = props.height < 150
    const m = { top: 10 + legendH, right: showLegend ? 64 : 12, bottom: 24, left: small ? 36 : 44 }
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h).attr('role', 'img').attr('aria-label', props.label)

    const xDomain = props.xMin || props.xMax ? [props.xMin, props.xMax] : d3.extent(xs)
    const x = numeric
      ? d3.scaleLinear().domain(xDomain).range([m.left, width - m.right])
      : d3.scalePoint().domain(xs.map(String)).range([m.left, width - m.right])
    const X = (v) => (numeric ? x(v) : x(String(v)))
    const ys = series.flatMap((s) => s.points.map((p) => p.y)).filter((v) => v != null)
    const yTop = props.yMax || d3.max(ys) || 1
    const y = d3.scaleLinear().domain([Math.min(0, d3.min(ys) ?? 0), yTop]).nice(small ? 2 : 4).range([h - m.bottom, m.top])

    svg.selectAll('g.grid').data([0]).join('g').attr('class', 'grid')
      .attr('transform', `translate(${m.left},0)`)
      .call(d3.axisLeft(y).ticks(small ? 2 : 4).tickSize(-(width - m.left - m.right)).tickFormat(compact))
      .call((g) => g.select('.domain').remove())
      .call((g) => g.selectAll('text').attr('x', -6))
    const maxTicks = Math.max(2, Math.floor((width - m.left - m.right) / 60))
    const xAxis = numeric
      ? d3.axisBottom(x).ticks(Math.min(maxTicks, xs.length)).tickFormat(d3.format('d'))
      : d3.axisBottom(x).tickValues(xs.map(String).filter((_, i) => i % Math.ceil(xs.length / maxTicks) === 0))
    svg.selectAll('g.x').data([0]).join('g').attr('class', 'x')
      .attr('transform', `translate(0,${h - m.bottom})`)
      .call(xAxis.tickSize(0).tickPadding(8))
      .call((g) => g.select('.domain').remove())
    svg.selectAll('line.base').data([0]).join('line').attr('class', 'base')
      .attr('x1', m.left).attr('x2', width - m.right).attr('y1', y(0)).attr('y2', y(0))

    // Solid up to the last full point; a partial (highlighted) final x is dashed.
    const hl = props.highlight
    const isHl = (p) => hl !== '' && String(p.x) === hl
    const line = d3.line().defined((p) => p.y != null).x((p) => X(p.x)).y((p) => y(p.y))
    const g = svg.selectAll('g.series').data(series, (s) => s.name).join('g').attr('class', 'series')
    g.selectAll('path.solid').data((s) => [s]).join('path').attr('class', 'solid')
      .attr('fill', 'none').attr('stroke', (s) => (multi ? s.color : 'var(--series-1)')).attr('stroke-width', small ? 1.5 : 2)
      .attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round')
      .transition().duration(t).attr('d', (s) => line(s.points.filter((p) => !isHl(p))))
    g.selectAll('path.partial').data((s) => {
      const i = s.points.findIndex(isHl)
      return i > 0 ? [[s.points[i - 1], s.points[i], s]] : []
    }).join('path').attr('class', 'partial')
      .attr('fill', 'none').attr('stroke', (d) => (multi ? d[2].color : 'var(--series-1)')).attr('stroke-width', 2)
      .attr('stroke-dasharray', '4 4').attr('d', (d) => line(d.slice(0, 2)))

    // Direct labels at each line's last point (2+ series), nudged apart.
    const ends = showLegend
      ? series.map((s) => {
          const last = [...s.points].reverse().find((p) => p.y != null)
          return last ? { s, x: X(last.x), y: y(last.y) } : null
        }).filter(Boolean).sort((a, b) => a.y - b.y)
      : []
    for (let i = 1; i < ends.length; i++) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 12)
    svg.selectAll('text.end').data(ends, (d) => d.s.name).join('text').attr('class', 'end label')
      .attr('x', (d) => d.x + 6).attr('y', (d) => d.y + 4).style('font-size', '11px').text((d) => d.s.name)

    // Legend (2+ series), one row above the plot.
    const lg = svg.selectAll('g.legend').data(showLegend ? [0] : []).join('g').attr('class', 'legend')
      .attr('transform', `translate(${m.left},4)`)
    let off = 0
    lg.selectAll('g.item').data(series, (s) => s.name).join((e) => {
      const it = e.append('g').attr('class', 'item')
      it.append('rect').attr('width', 14).attr('height', 3).attr('y', 6).attr('rx', 1.5)
      it.append('text').attr('x', 18).attr('y', 11)
      return it
    }).each(function (s) {
      const it = d3.select(this).attr('transform', `translate(${off},0)`)
      it.select('rect').attr('fill', s.color)
      it.select('text').text(s.name)
      off += 26 + s.name.length * 6.5
    })

    // Crosshair + tooltip with every series' value at the nearest x.
    const cross = svg.selectAll('line.cross').data([0]).join('line').attr('class', 'cross')
      .attr('y1', m.top).attr('y2', h - m.bottom).attr('visibility', 'hidden')
    const nearest = (px) => {
      let best = xs[0], bd = Infinity
      for (const v of xs) { const d = Math.abs(X(v) - px); if (d < bd) { bd = d; best = v } }
      return best
    }
    svg.selectAll('rect.hit').data([0]).join('rect').attr('class', 'hit')
      .attr('x', m.left).attr('y', m.top).attr('width', width - m.left - m.right).attr('height', h - m.top - m.bottom)
      .on('pointermove', (evt) => {
        const [px] = d3.pointer(evt, svg.node())
        const v = nearest(px)
        cross.attr('x1', X(v)).attr('x2', X(v)).attr('visibility', 'visible')
        const vals = series.map((s) => [s.name, s.points.find((p) => p.x === v)?.y]).filter(([, yv]) => yv != null)
        const top = d3.min(vals, ([, yv]) => y(yv)) ?? m.top
        const unit = props.unit ? ` ${props.unit.trim()}` : ''
        const body = vals.map(([n, yv]) => (multi ? `${n}: ` : '') + commas(Math.round(yv * 100) / 100) + unit).join(' · ')
        tooltip.show(X(v), top, `${v}${isHl({ x: v }) ? ' (partial)' : ''}: ${body}`)
      })
      .on('pointerleave', () => { cross.attr('visibility', 'hidden'); tooltip.hide() })
  },
})
