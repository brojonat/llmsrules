// d3 charts as Datastar Rocket web components (pattern from the
// python-warehouse-dashboard template).
//
// The server renders each chart as a bare custom element whose attributes
// carry the data; later morphs change those attributes and d3 redraws.
// Components draw into an open shadow root, so a page morph only diffs the
// host's attributes, never d3's SVG. Colors come from the page's CSS custom
// properties, which inherit through the shadow boundary.

import { rocket } from 'datastar'

// The figures carousel (templates/figures.html): which key is showing, and the next one either way.
// Keys come from the server; the current one ($fig) is per browser, so it can name a figure that's gone.
window.figAt = (keys, cur) => (keys.includes(cur) ? cur : keys[0])
window.figStep = (keys, cur, d) => keys[(Math.max(0, keys.indexOf(window.figAt(keys, cur))) + d + keys.length) % keys.length]
import * as d3 from 'd3'

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
const duration = () => (reduceMotion.matches ? 0 : 200)

const compact = (v) => {
  if (v == null || Number.isNaN(v)) return '–'
  const a = Math.abs(v)
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (a >= 1e4) return `${(v / 1e3).toFixed(1)}K`
  if (a >= 100) return d3.format(',.0f')(v)
  if (a >= 1) return d3.format('.3~g')(v)
  return d3.format('.2~g')(v)
}

const STYLE = `
  :host { display: block; position: relative; }
  svg { display: block; width: 100%; overflow: visible; }
  text { font: 11px system-ui, sans-serif; fill: var(--ink-muted); }
  .grid line { stroke: var(--grid); }
  .grid .zero { stroke: var(--baseline); }
  .label { font-size: 12px; fill: var(--ink); font-variant-numeric: tabular-nums; }
  .cross { stroke: var(--ink-muted); stroke-dasharray: 2 2; }
  .hit { fill: transparent; }
  .tip { position: absolute; pointer-events: none; white-space: nowrap; z-index: 1;
         font: 13px/1.3 system-ui, sans-serif; padding: .3rem .5rem; border-radius: 6px;
         color: var(--ink); background: var(--surface);
         border: 1px solid color-mix(in srgb, var(--ink) 20%, transparent);
         box-shadow: 0 2px 8px rgb(0 0 0 / .15); transform: translate(-50%, calc(-100% - 8px)); }
  .tip[hidden] { display: none; }
`

// Shadow root with an <svg> and a tooltip; redraw on prop change and resize.
const chart = (tag, { props, draw }) =>
  rocket(tag, {
    mode: 'open',
    props,
    renderOnPropChange: false,
    render: ({ html }) => html`<style>${STYLE}</style><svg></svg><div class="tip" hidden></div>`,
    onFirstRender: ({ host, props, observeProps, cleanup }) => {
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
        hide() { tip.hidden = true },
      }
      let width = 0
      const redraw = (animate) => {
        width = host.clientWidth || width
        if (width) draw({ svg, props, width, tooltip, t: animate ? duration() : 0 })
      }
      observeProps(() => redraw(true))
      const ro = new ResizeObserver(() => { if (host.clientWidth !== width) redraw(false) })
      ro.observe(host)
      cleanup(() => ro.disconnect())
      redraw(false)
    },
  })

// Posterior intervals per parameter: 90% thin line, 50% thick rounded bar,
// median dot, truth as a hollow ink diamond. rows: [{name, q05, q25, q50, q75, q95, truth}]
chart('chart-forest', {
  props: ({ json, string }) => ({
    rows: json.default(() => []),
    label: string.default('posterior intervals'),
  }),
  draw: ({ svg, props, width, tooltip, t }) => {
    const rows = props.rows
    const rowH = 22
    // Room for the longest label (12px text, ~6.6px per char), e.g. sigma[support_calls].
    const longest = d3.max(rows, (r) => r.name.length) ?? 0
    const m = { top: 8, right: 16, bottom: 24, left: Math.min(width / 2, 16 + 6.6 * longest) }
    const h = m.top + m.bottom + rows.length * rowH
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h).attr('role', 'img').attr('aria-label', props.label)
    const lo = d3.min(rows, (r) => Math.min(r.q05, r.truth ?? r.q05)) ?? -1
    const hi = d3.max(rows, (r) => Math.max(r.q95, r.truth ?? r.q95)) ?? 1
    const x = d3.scaleLinear().domain([Math.min(lo, 0), Math.max(hi, 0)]).nice().range([m.left, width - m.right])
    const y = d3.scaleBand().domain(rows.map((r) => r.name)).range([m.top, h - m.bottom]).padding(0.3)
    const cy = (r) => y(r.name) + y.bandwidth() / 2

    svg.selectAll('g.grid').data([0]).join('g').attr('class', 'grid')
      .attr('transform', `translate(0,${h - m.bottom})`)
      .call(d3.axisBottom(x).ticks(Math.max(2, Math.floor((width - m.left - m.right) / 70))).tickSize(-(h - m.top - m.bottom)).tickFormat(compact))
      .call((g) => g.select('.domain').remove())
      .call((g) => g.selectAll('.tick line').classed('zero', (d) => d === 0))
      .call((g) => g.selectAll('text').attr('dy', 10))
    svg.selectAll('text.name').data(rows, (r) => r.name).join('text').attr('class', 'name label')
      .attr('x', m.left - 10).attr('text-anchor', 'end').attr('y', (r) => cy(r) + 4).text((r) => r.name)

    const g = svg.selectAll('g.row').data(rows, (r) => r.name).join((e) => {
      const r = e.append('g').attr('class', 'row')
      r.append('line').attr('class', 'i90').attr('stroke', 'var(--series-1)').attr('stroke-width', 2).attr('stroke-linecap', 'round')
      r.append('line').attr('class', 'i50').attr('stroke', 'var(--series-1)').attr('stroke-width', 7).attr('stroke-linecap', 'round')
      r.append('circle').attr('class', 'med').attr('r', 4.5).attr('fill', 'var(--surface)').attr('stroke', 'var(--series-1)').attr('stroke-width', 2)
      r.append('path').attr('class', 'truth').attr('d', d3.symbol(d3.symbolDiamond, 64)()).attr('fill', 'none')
        .attr('stroke', 'var(--ink)').attr('stroke-width', 1.5)
      return r
    })
    g.select('.i90').transition().duration(t).attr('x1', (r) => x(r.q05)).attr('x2', (r) => x(r.q95)).attr('y1', cy).attr('y2', cy)
    g.select('.i50').transition().duration(t).attr('x1', (r) => x(r.q25)).attr('x2', (r) => x(r.q75)).attr('y1', cy).attr('y2', cy)
    g.select('.med').transition().duration(t).attr('cx', (r) => x(r.q50)).attr('cy', cy)
    g.select('.truth').attr('visibility', (r) => (r.truth == null ? 'hidden' : 'visible'))
      .transition().duration(t).attr('transform', (r) => `translate(${x(r.truth ?? 0)},${cy(r)})`)

    // Hover: whole row is the hit target.
    svg.selectAll('rect.hit').data(rows, (r) => r.name).join('rect').attr('class', 'hit')
      .attr('x', 0).attr('width', width).attr('y', (r) => y(r.name) - (y.step() - y.bandwidth()) / 2).attr('height', y.step())
      .on('pointermove', (evt, r) => {
        const inside = r.truth != null && r.truth >= r.q05 && r.truth <= r.q95
        const truth = r.truth == null ? '' : ` · truth ${compact(r.truth)}${inside ? '' : ' (outside 90%)'}`
        tooltip.show(x(r.q50), cy(r) - 6, `${r.name}: ${compact(r.q50)} [${compact(r.q05)}, ${compact(r.q95)}]${truth}`)
      })
      .on('pointerleave', () => tooltip.hide())
  },
})

// One parameter across fits: 90% band, median line, truth dashed.
// points: [[rows fed, q05, q50, q95, truth], ...]. yMin/yMax shared across facets.
chart('chart-track', {
  props: ({ json, string, number }) => ({
    points: json.default(() => []),
    label: string.default(''),
    yMin: number.default(0),
    yMax: number.default(0),
    height: number.default(120),
  }),
  draw: ({ svg, props, width, tooltip, t }) => {
    const pts = props.points.map(([i, lo, mid, hi, truth]) => ({ i, lo, mid, hi, truth }))
    const h = props.height
    const m = { top: 20, right: 12, bottom: 22, left: 36 }
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h).attr('role', 'img').attr('aria-label', `${props.label} by rows fed`)
    const x = d3.scaleLinear().domain(d3.extent(pts, (p) => p.i)).range([m.left, width - m.right])
    const yd = props.yMin || props.yMax ? [props.yMin, props.yMax] : [d3.min(pts, (p) => Math.min(p.lo, p.truth ?? p.lo)), d3.max(pts, (p) => Math.max(p.hi, p.truth ?? p.hi))]
    const y = d3.scaleLinear().domain(yd).nice(3).range([h - m.bottom, m.top])

    svg.selectAll('text.title').data([0]).join('text').attr('class', 'title label').attr('x', m.left).attr('y', 12).text(props.label)
    svg.selectAll('g.grid').data([0]).join('g').attr('class', 'grid').attr('transform', `translate(${m.left},0)`)
      .call(d3.axisLeft(y).ticks(3).tickSize(-(width - m.left - m.right)).tickFormat(compact))
      .call((g) => g.select('.domain').remove())
      .call((g) => g.selectAll('.tick line').classed('zero', (d) => d === 0))
    svg.selectAll('g.xaxis').data([0]).join('g').attr('class', 'xaxis grid').attr('transform', `translate(0,${h - m.bottom})`)
      .call(d3.axisBottom(x).tickValues(x.ticks(Math.max(2, Math.floor((width - m.left - m.right) / 80))).filter(Number.isInteger)).tickSize(3).tickFormat(compact))
      .call((g) => g.select('.domain').remove())

    const area = d3.area().x((p) => x(p.i)).y0((p) => y(p.lo)).y1((p) => y(p.hi))
    const line = (k) => d3.line().defined((p) => p[k] != null).x((p) => x(p.i)).y((p) => y(p[k]))
    svg.selectAll('path.band').data([pts]).join('path').attr('class', 'band')
      .attr('fill', 'color-mix(in srgb, var(--series-1) 30%, transparent)').transition().duration(t).attr('d', area)
    svg.selectAll('path.mid').data([pts]).join('path').attr('class', 'mid').attr('fill', 'none')
      .attr('stroke', 'var(--series-1)').attr('stroke-width', 2).attr('stroke-linejoin', 'round')
      .transition().duration(t).attr('d', line('mid'))
    svg.selectAll('path.truth').data([pts]).join('path').attr('class', 'truth').attr('fill', 'none')
      .attr('stroke', 'var(--ink)').attr('stroke-width', 1.5).attr('stroke-dasharray', '4 3')
      .transition().duration(t).attr('d', line('truth'))
    // One fit has no band or line to draw: show its 90% interval as a bar. Every fit gets a dot.
    svg.selectAll('line.solo').data(pts.length === 1 ? pts : []).join('line').attr('class', 'solo')
      .attr('stroke', 'var(--series-1)').attr('stroke-width', 3).attr('stroke-linecap', 'round')
      .attr('x1', (p) => x(p.i)).attr('x2', (p) => x(p.i)).attr('y1', (p) => y(p.lo)).attr('y2', (p) => y(p.hi))
    svg.selectAll('circle.pt').data(pts).join('circle').attr('class', 'pt').attr('r', pts.length > 60 ? 0 : 2.5)
      .attr('fill', 'var(--series-1)').transition().duration(t).attr('cx', (p) => x(p.i)).attr('cy', (p) => y(p.mid))

    const cross = svg.selectAll('line.cross').data([0]).join('line').attr('class', 'cross')
      .attr('y1', m.top).attr('y2', h - m.bottom).attr('visibility', 'hidden')
    svg.selectAll('rect.hit').data([0]).join('rect').attr('class', 'hit')
      .attr('x', m.left).attr('y', m.top).attr('width', Math.max(0, width - m.left - m.right)).attr('height', h - m.top - m.bottom)
      .on('pointermove', (evt) => {
        const [px] = d3.pointer(evt, svg.node())
        const p = pts[d3.minIndex(pts, (q) => Math.abs(x(q.i) - px))]
        if (!p) return
        cross.attr('x1', x(p.i)).attr('x2', x(p.i)).attr('visibility', 'visible')
        const truth = p.truth == null ? '' : ` · truth ${compact(p.truth)}`
        tooltip.show(x(p.i), y(p.hi), `${compact(p.i)} rows: ${compact(p.mid)} [${compact(p.lo)}, ${compact(p.hi)}]${truth}`)
      })
      .on('pointerleave', () => { cross.attr('visibility', 'hidden'); tooltip.hide() })
  },
})

// Tile sparkline: one series, last point marked, crosshair tooltip.
chart('chart-spark', {
  props: ({ json, string, number }) => ({
    series: json.default(() => []),
    unit: string.default(''),
    label: string.default('trend'),
    height: number.default(36),
    ref: number.default(NaN), // optional reference line (e.g. 0.9 coverage target)
  }),
  draw: ({ svg, props, width, tooltip }) => {
    const ys = props.series
    const h = props.height
    const m = { top: 4, right: 4, bottom: 4, left: 4 }
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h).attr('role', 'img').attr('aria-label', props.label)
    const x = d3.scaleLinear().domain([0, Math.max(1, ys.length - 1)]).range([m.left, width - m.right])
    const ext = d3.extent([...ys, ...(Number.isNaN(props.ref) ? [] : [props.ref])])
    const y = d3.scaleLinear().domain(ext[0] === ext[1] ? [ext[0] - 1, ext[1] + 1] : ext).range([h - m.bottom, m.top])
    svg.selectAll('line.ref').data(Number.isNaN(props.ref) ? [] : [props.ref]).join('line').attr('class', 'ref')
      .attr('stroke', 'var(--baseline)').attr('stroke-dasharray', '3 3')
      .attr('x1', m.left).attr('x2', width - m.right).attr('y1', y).attr('y2', y)
    svg.selectAll('path.line').data([ys]).join('path').attr('class', 'line').attr('fill', 'none')
      .attr('stroke', 'var(--series-1)').attr('stroke-width', 1.5).attr('stroke-linejoin', 'round')
      .attr('d', d3.line().x((_, i) => x(i)).y((v) => y(v)))
    svg.selectAll('circle.now').data(ys.length ? [ys.length - 1] : []).join('circle').attr('class', 'now')
      .attr('r', 3).attr('fill', 'var(--series-1)').attr('cx', x).attr('cy', (i) => y(ys[i]))
    const cross = svg.selectAll('line.cross').data([0]).join('line').attr('class', 'cross')
      .attr('y1', 0).attr('y2', h).attr('visibility', 'hidden')
    svg.selectAll('rect.hit').data([0]).join('rect').attr('class', 'hit').attr('width', width).attr('height', h)
      .on('pointermove', (evt) => {
        const [px] = d3.pointer(evt, svg.node())
        const i = Math.max(0, Math.min(ys.length - 1, Math.round(x.invert(px))))
        cross.attr('x1', x(i)).attr('x2', x(i)).attr('visibility', 'visible')
        tooltip.show(x(i), 0, `fit ${i + 1}: ${compact(ys[i])}${props.unit}`)
      })
      .on('pointerleave', () => { cross.attr('visibility', 'hidden'); tooltip.hide() })
  },
})

// The PyMC model graph: DOT source from pm.model_to_graphviz, laid out by
// Graphviz compiled to WASM (~800 KB, imported only when this element is on
// the page). The server sends the DOT once per model; restyled with the page
// tokens so it follows light/dark.
const GRAPH_STYLE = `
  :host { display: block; overflow-x: auto; }
  svg { display: block; max-width: 100%; max-height: 420px; width: auto; height: auto; margin: 0 auto; }
  text { font-family: system-ui, sans-serif; fill: var(--ink); }
  .graph > polygon { fill: transparent; stroke: none; }
  .cluster path, .cluster polygon { stroke: var(--baseline); fill: none; }
  .cluster text { fill: var(--ink-muted); font-size: 12px; }
  .node path, .node ellipse, .node polygon { stroke: var(--ink-muted); fill: var(--surface); }
  .node [fill="lightgrey"] { fill: var(--grid); }
  .edge path { stroke: var(--ink-muted); }
  .edge polygon { stroke: var(--ink-muted); fill: var(--ink-muted); }
  .err { color: var(--ink-muted); font: 14px system-ui, sans-serif; }
`
let graphviz // one WASM instance per page, loaded on first use
rocket('model-graph', {
  mode: 'open',
  props: ({ string }) => ({ dot: string.default('') }),
  renderOnPropChange: false,
  render: ({ html }) => html`<style>${GRAPH_STYLE}</style><div class="out"></div>`,
  onFirstRender: ({ host, props, observeProps }) => {
    const out = host.shadowRoot.querySelector('.out')
    const draw = async () => {
      if (!props.dot) { out.replaceChildren(); return }
      try {
        graphviz ??= import('graphviz').then((m) => m.Graphviz.load())
        out.innerHTML = (await graphviz).dot(props.dot)
        out.querySelector('svg')?.setAttribute('role', 'img')
        out.querySelector('svg')?.setAttribute('aria-label', 'PyMC model graph')
      } catch (e) {
        out.innerHTML = '<p class="err"></p>'
        out.firstChild.textContent = `Could not render the model graph: ${e}`
      }
    }
    observeProps(draw)
    draw()
  },
})

// A 2-D variable as small multiples: one forest column per column label, one
// row per row label, all on one x scale so columns compare directly. Columns
// wrap into bands on narrow screens (each band repeats the row labels).
// rows: [{name, row, col, q05, q25, q50, q75, q95, truth}]
chart('chart-grid', {
  props: ({ json, string }) => ({
    rows: json.default(() => []),
    rowLabels: json.default(() => []),
    colLabels: json.default(() => []),
    label: string.default('posterior intervals by row and column'),
  }),
  draw: ({ svg, props, width, tooltip, t }) => {
    const { rowLabels: groups, colLabels: features } = props
    const byKey = new Map(props.rows.map((r) => [`${r.row}\u0000${r.col}`, r]))
    const labelW = 72
    const minCol = 120
    const perBand = Math.max(1, Math.min(features.length, Math.floor((width - labelW) / minCol)))
    const bands = d3.range(0, features.length, perBand).map((i) => features.slice(i, i + perBand))
    const rowH = 16
    const head = 22
    const axisH = 20
    const bandH = head + groups.length * rowH + axisH
    const gap = 16
    const h = bands.length * bandH + (bands.length - 1) * gap
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h).attr('role', 'img').attr('aria-label', props.label)

    const vals = props.rows.flatMap((r) => [r.q05, r.q95, r.truth]).filter((v) => v != null)
    const colW = (width - labelW) / perBand
    const pad = 10
    const x = d3.scaleLinear().domain(d3.extent([0, ...vals])).nice().range([pad, colW - pad])
    const y = d3.scaleBand().domain(groups).range([head, head + groups.length * rowH]).padding(0.25)
    const cy = (g) => y(g) + y.bandwidth() / 2

    const band = svg.selectAll('g.band').data(bands).join('g').attr('class', 'band')
      .attr('transform', (_, i) => `translate(0,${i * (bandH + gap)})`)
    band.selectAll('text.grp').data(groups).join('text').attr('class', 'grp label')
      .attr('x', labelW - 8).attr('text-anchor', 'end').attr('y', (g) => cy(g) + 4).style('font-size', '11px').text((g) => g)

    const col = band.selectAll('g.col').data((fs) => fs, (f) => f).join('g').attr('class', 'col')
      .attr('transform', (_, i) => `translate(${labelW + i * colW},0)`)
    col.selectAll('text.title').data((f) => [f]).join('text').attr('class', 'title label')
      .attr('x', colW / 2).attr('text-anchor', 'middle').attr('y', 12).text((f) => f)
    col.selectAll('g.grid').data([0]).join('g').attr('class', 'grid')
      .attr('transform', `translate(0,${head + groups.length * rowH})`)
      .call(d3.axisBottom(x).ticks(Math.max(2, Math.floor(colW / 45))).tickSize(-groups.length * rowH).tickFormat(compact))
      .call((g) => g.select('.domain').remove())
      .call((g) => g.selectAll('.tick line').classed('zero', (d) => d === 0))

    const cells = col.selectAll('g.cell')
      .data((f) => groups.map((g) => byKey.get(`${g}\u0000${f}`)).filter(Boolean), (r) => r.row)
      .join((e) => {
        const c = e.append('g').attr('class', 'cell')
        c.append('line').attr('class', 'i90').attr('stroke', 'var(--series-1)').attr('stroke-width', 1.5).attr('stroke-linecap', 'round')
        c.append('line').attr('class', 'i50').attr('stroke', 'var(--series-1)').attr('stroke-width', 5).attr('stroke-linecap', 'round')
        c.append('path').attr('class', 'truth').attr('d', d3.symbol(d3.symbolDiamond, 36)()).attr('fill', 'none')
          .attr('stroke', 'var(--ink)').attr('stroke-width', 1.25)
        return c
      })
    cells.select('.i90').transition().duration(t).attr('x1', (r) => x(r.q05)).attr('x2', (r) => x(r.q95))
      .attr('y1', (r) => cy(r.row)).attr('y2', (r) => cy(r.row))
    cells.select('.i50').transition().duration(t).attr('x1', (r) => x(r.q25)).attr('x2', (r) => x(r.q75))
      .attr('y1', (r) => cy(r.row)).attr('y2', (r) => cy(r.row))
    cells.select('.truth').attr('visibility', (r) => (r.truth == null ? 'hidden' : 'visible'))
      .transition().duration(t).attr('transform', (r) => `translate(${x(r.truth ?? 0)},${cy(r.row)})`)

    // Hover: each cell's full row strip within its column.
    col.selectAll('rect.hit').data((f) => groups.map((g) => byKey.get(`${g}\u0000${f}`)).filter(Boolean), (r) => r.row)
      .join('rect').attr('class', 'hit')
      .attr('x', 0).attr('width', colW).attr('y', (r) => y(r.row) - (y.step() - y.bandwidth()) / 2).attr('height', y.step())
      .on('pointermove', function (evt, r) {
        const [px, py] = d3.pointer(evt, svg.node())
        const inside = r.truth != null && r.truth >= r.q05 && r.truth <= r.q95
        const truth = r.truth == null ? '' : ` · truth ${compact(r.truth)}${inside ? '' : ' (outside 90%)'}`
        tooltip.show(px, py - 6, `${r.name}: ${compact(r.q50)} [${compact(r.q05)}, ${compact(r.q95)}]${truth}`)
      })
      .on('pointerleave', () => tooltip.hide())
  },
})

// The figures carousel's diagnostics (templates/figures.html), drawn from the data plots.py
// reduces each one to: <figure-chart src="/figures/ID.json">. The element fetches its data once
// (ids are immutable) and redraws on resize, like an <img> that follows the page's theme.
// Kinds: calibration | rootogram | density (predictive checks), prior_posterior, trace, rank.
const FIG_STYLE = `${STYLE}
  .err { font: 14px system-ui, sans-serif; color: var(--ink-muted); padding: 1rem 0; }
`
const band = 'color-mix(in srgb, var(--series-1) 28%, transparent)'

// A legend row inside the SVG, so a saved PNG keeps it. items: [{label, mark: line|dash|band|dot|bar}]
const legend = (svg, items, x, y) => {
  const g = svg.selectAll('g.legend').data([0]).join('g').attr('class', 'legend').attr('transform', `translate(${x},${y})`)
  g.selectAll('*').remove()
  let at = 0
  for (const it of items) {
    const e = g.append('g').attr('transform', `translate(${at},0)`)
    if (it.mark === 'band') e.append('rect').attr('y', -6).attr('width', 18).attr('height', 10).attr('rx', 2).attr('fill', band)
    else if (it.mark === 'bar') e.append('rect').attr('y', -6).attr('width', 12).attr('height', 10).attr('rx', 2).attr('fill', 'var(--series-1)')
    else if (it.mark === 'dot') e.append('circle').attr('cx', 6).attr('cy', -1).attr('r', 4).attr('fill', 'var(--ink)')
    else e.append('line').attr('x2', 18).attr('y1', -1).attr('y2', -1).attr('stroke-width', 2)
      .attr('stroke', it.color ?? 'var(--series-1)').attr('stroke-dasharray', it.mark === 'dash' ? '4 3' : null)
    const t = e.append('text').attr('class', 'label').attr('x', it.mark === 'dot' || it.mark === 'bar' ? 16 : 24).attr('y', 3).text(it.label)
    at += (it.mark === 'dot' || it.mark === 'bar' ? 16 : 24) + t.node().getComputedTextLength() + 16
  }
  return 18 // height used
}

// Small multiples: as many columns of at least minW as fit.
const multiples = (n, width, minW) => {
  const cols = Math.max(1, Math.min(n, Math.floor(width / minW)))
  return { cols, w: width / cols }
}

const yAxis = (g, y, w, ticks = 3, fmt = compact) => g.call(d3.axisLeft(y).ticks(ticks).tickSize(-w).tickFormat(fmt))
  .call((a) => a.select('.domain').remove()).call((a) => a.selectAll('.tick line').classed('zero', (d) => d === 0))
const xAxis = (g, x, ticks, fmt = compact) => g.call(d3.axisBottom(x).ticks(ticks).tickSizeOuter(0).tickFormat(fmt))
  .call((a) => a.select('.domain').attr('stroke', 'var(--baseline)'))

const DRAW = {
  // Rows binned by predicted probability: observed share (dot) vs the predictive 90% band; on the diagonal = calibrated.
  calibration(svg, data, width, tip) {
    const m = { top: 30, right: 12, bottom: 34, left: 44 }
    const h = 320
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h)
    const top = legend(svg, [{ label: 'observed share', mark: 'dot' }, { label: 'predictive 90%', mark: 'band' }, { label: 'perfectly calibrated', mark: 'dash', color: 'var(--baseline)' }], m.left, 12)
    const all = data.bins.flatMap((b) => [b[0], b[1], b[2], b[3]])
    const ext = [Math.min(0, d3.min(all)), Math.max(1, d3.max(all))]
    const x = d3.scaleLinear().domain(ext).range([m.left, width - m.right])
    const y = d3.scaleLinear().domain(ext).range([h - m.bottom, m.top + top - 8])
    yAxis(svg.append('g').attr('class', 'grid').attr('transform', `translate(${m.left},0)`), y, width - m.left - m.right, 5)
    xAxis(svg.append('g').attr('transform', `translate(0,${h - m.bottom})`), x, 5)
    svg.append('text').attr('x', width - m.right).attr('y', h - 4).attr('text-anchor', 'end').text('predicted probability')
    svg.append('line').attr('x1', x(ext[0])).attr('y1', y(ext[0])).attr('x2', x(ext[1])).attr('y2', y(ext[1]))
      .attr('stroke', 'var(--baseline)').attr('stroke-dasharray', '4 3')
    svg.selectAll('line.band').data(data.bins).join('line').attr('class', 'band').attr('stroke', band).attr('stroke-width', 10)
      .attr('stroke-linecap', 'round').attr('x1', (b) => x(b[0])).attr('x2', (b) => x(b[0])).attr('y1', (b) => y(b[2])).attr('y2', (b) => y(b[3]))
    svg.selectAll('circle.obs').data(data.bins).join('circle').attr('class', 'obs').attr('r', 4.5).attr('fill', 'var(--ink)')
      .attr('stroke', 'var(--surface)').attr('stroke-width', 2).attr('cx', (b) => x(b[0])).attr('cy', (b) => y(b[1]))
    svg.selectAll('rect.hit').data(data.bins).join('rect').attr('class', 'hit')
      .attr('x', (b) => x(b[0]) - 10).attr('width', 20).attr('y', m.top).attr('height', h - m.top - m.bottom)
      .on('pointermove', (_, b) => tip.show(x(b[0]), y(Math.max(b[1], b[3])) - 6,
        `predicted ${compact(b[0])} · observed ${compact(b[1])} · predictive 90% [${compact(b[2])}, ${compact(b[3])}] · ${compact(b[4])} rows`))
      .on('pointerleave', () => tip.hide())
  },

  // How often each value occurs, on a square-root scale so small counts stay visible: observed
  // (bars) vs expected (dot) and its predictive 90% interval.
  rootogram(svg, data, width, tip) {
    const m = { top: 30, right: 12, bottom: 34, left: 44 }
    const h = 320
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h)
    const top = legend(svg, [{ label: 'observed', mark: 'bar' }, { label: 'expected', mark: 'dot' }, { label: 'predictive 90%', mark: 'line', color: 'var(--ink)' }], m.left, 12)
    const rows = data.counts
    const x = d3.scaleBand().domain(rows.map((r) => r[0])).range([m.left, width - m.right]).padding(0.15)
    const y = d3.scaleSqrt().domain([0, d3.max(rows, (r) => Math.max(r[1], r[4]))]).nice().range([h - m.bottom, m.top + top - 8])
    yAxis(svg.append('g').attr('class', 'grid').attr('transform', `translate(${m.left},0)`), y, width - m.left - m.right, 4)
    const every = Math.ceil(rows.length / Math.max(2, Math.floor((width - m.left - m.right) / 36)))
    svg.append('g').attr('transform', `translate(0,${h - m.bottom})`)
      .call(d3.axisBottom(x).tickValues(x.domain().filter((_, i) => i % every === 0)).tickSizeOuter(0))
      .call((a) => a.select('.domain').attr('stroke', 'var(--baseline)'))
    svg.append('text').attr('x', m.left + 4).attr('y', m.top + top - 12).text('count (√ scale)')
    svg.selectAll('rect.bar').data(rows).join('rect').attr('class', 'bar').attr('fill', 'var(--series-1)').attr('rx', 2)
      .attr('x', (r) => x(r[0])).attr('width', x.bandwidth()).attr('y', (r) => y(r[1])).attr('height', (r) => y(0) - y(r[1]))
    const cx = (r) => x(r[0]) + x.bandwidth() / 2
    svg.selectAll('line.iv').data(rows).join('line').attr('class', 'iv').attr('stroke', 'var(--ink)').attr('stroke-width', 2)
      .attr('x1', cx).attr('x2', cx).attr('y1', (r) => y(r[3])).attr('y2', (r) => y(r[4]))
    svg.selectAll('circle.exp').data(rows).join('circle').attr('class', 'exp').attr('r', 4).attr('fill', 'var(--ink)')
      .attr('stroke', 'var(--surface)').attr('stroke-width', 2).attr('cx', cx).attr('cy', (r) => y(r[2]))
    svg.selectAll('rect.hit').data(rows).join('rect').attr('class', 'hit')
      .attr('x', (r) => x(r[0])).attr('width', x.step()).attr('y', m.top).attr('height', h - m.top - m.bottom)
      .on('pointermove', (_, r) => tip.show(cx(r), y(Math.max(r[1], r[4])) - 6,
        `${r[0]}: observed ${compact(r[1])} · expected ${compact(r[2])} [${compact(r[3])}, ${compact(r[4])}]`))
      .on('pointerleave', () => tip.hide())
  },

  // The observed density against the band of predictive draws' densities.
  density(svg, data, width, tip) {
    const m = { top: 30, right: 12, bottom: 28, left: 44 }
    const h = 300
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h)
    const top = legend(svg, [{ label: 'observed', mark: 'line', color: 'var(--ink)' }, { label: 'predictive median', mark: 'line' }, { label: 'predictive 90%', mark: 'band' }], m.left, 12)
    const g = data.grid
    const x = d3.scaleLinear().domain(d3.extent(g)).range([m.left, width - m.right])
    const y = d3.scaleLinear().domain([0, d3.max([...data.hi, ...data.observed])]).nice().range([h - m.bottom, m.top + top - 8])
    yAxis(svg.append('g').attr('class', 'grid').attr('transform', `translate(${m.left},0)`), y, width - m.left - m.right, 3)
    xAxis(svg.append('g').attr('transform', `translate(0,${h - m.bottom})`), x, Math.max(2, Math.floor(width / 90)))
    svg.append('path').attr('fill', band).attr('d', d3.area().x((_, i) => x(g[i])).y0((_, i) => y(data.lo[i])).y1((_, i) => y(data.hi[i]))(g))
    svg.append('path').attr('fill', 'none').attr('stroke', 'var(--series-1)').attr('stroke-width', 2).attr('d', d3.line().x((_, i) => x(g[i])).y((_, i) => y(data.mid[i]))(g))
    svg.append('path').attr('fill', 'none').attr('stroke', 'var(--ink)').attr('stroke-width', 2).attr('d', d3.line().x((_, i) => x(g[i])).y((_, i) => y(data.observed[i]))(g))
    crosshair(svg, x, g, m, h, tip, (i) => `${compact(g[i])}: observed ${compact(data.observed[i])} · predictive ${compact(data.mid[i])} [${compact(data.lo[i])}, ${compact(data.hi[i])}]`, (i) => y(Math.max(data.hi[i], data.observed[i])))
  },

  // Small multiples, one per scalar: the prior's density (dashed) under the posterior's.
  prior_posterior(svg, data, width, tip) {
    const { cols, w } = multiples(data.panels.length, width, 220)
    const ph = 120, head = 26
    const rows = Math.ceil(data.panels.length / cols)
    const h = head + rows * ph
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h)
    legend(svg, [{ label: 'posterior', mark: 'band' }, { label: 'prior', mark: 'dash', color: 'var(--ink-muted)' }], 8, 12)
    data.panels.forEach((p, k) => {
      const g = svg.append('g').attr('transform', `translate(${(k % cols) * w},${head + Math.floor(k / cols) * ph})`)
      const m = { top: 18, right: 10, bottom: 22, left: 10 }
      const x = d3.scaleLinear().domain(d3.extent(p.grid)).range([m.left, w - m.right])
      const y = d3.scaleLinear().domain([0, d3.max(p.posterior)]).range([ph - m.bottom, m.top]) // prior may run off the top: it's context
      g.append('text').attr('class', 'label').attr('x', m.left).attr('y', 12).text(p.name)
      xAxis(g.append('g').attr('transform', `translate(0,${ph - m.bottom})`), x, Math.max(2, Math.floor(w / 80)))
      const clip = `clip-${k}-${Math.random().toString(36).slice(2)}`
      g.append('clipPath').attr('id', clip).append('rect').attr('x', m.left).attr('y', m.top).attr('width', w - m.left - m.right).attr('height', ph - m.top - m.bottom)
      const at = (ys) => (_, i) => y(ys[i])
      g.append('path').attr('clip-path', `url(#${clip})`).attr('fill', band).attr('stroke', 'var(--series-1)').attr('stroke-width', 2)
        .attr('d', d3.area().x((_, i) => x(p.grid[i])).y0(y(0)).y1(at(p.posterior))(p.grid))
      g.append('path').attr('clip-path', `url(#${clip})`).attr('fill', 'none').attr('stroke', 'var(--ink-muted)').attr('stroke-width', 1.5)
        .attr('stroke-dasharray', '4 3').attr('d', d3.line().x((_, i) => x(p.grid[i])).y(at(p.prior))(p.grid))
      g.append('rect').attr('class', 'hit').attr('x', m.left).attr('y', m.top).attr('width', w - m.left - m.right).attr('height', ph - m.top - m.bottom)
        .on('pointermove', (evt) => {
          const [px] = d3.pointer(evt, g.node())
          const i = d3.minIndex(p.grid, (v) => Math.abs(x(v) - px))
          const [sx, sy] = d3.pointer(evt, svg.node())
          tip.show(sx, sy - 10, `${p.name} = ${compact(p.grid[i])}: posterior ${compact(p.posterior[i])} · prior ${compact(p.prior[i])}`)
        })
        .on('pointerleave', () => tip.hide())
    })
  },

  // One row per scalar: each chain's density (left) and its draws in order (right). Chains that
  // mix overlap into one fuzzy band (the caterpillar); a chain off on its own is a problem.
  trace(svg, data, width, tip) {
    const rowH = 74, head = 22
    const h = head + data.panels.length * rowH
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h)
    const split = Math.max(140, Math.min(320, width * 0.3))
    svg.append('text').attr('x', 8).attr('y', 14).text('density by chain')
    svg.append('text').attr('x', split + 8).attr('y', 14).text('draws by chain, in order')
    data.panels.forEach((p, k) => {
      const g = svg.append('g').attr('transform', `translate(0,${head + k * rowH})`)
      const m = { top: 16, bottom: 6 }
      const values = p.draws.flat()
      const x = d3.scaleLinear().domain(d3.extent(p.grid)).range([8, split - 12])
      const yk = d3.scaleLinear().domain([0, d3.max(p.kde.flat())]).range([rowH - m.bottom, m.top])
      const n = p.draws[0].length
      const xt = d3.scaleLinear().domain([0, n - 1]).range([split + 8, width - 8])
      const yt = d3.scaleLinear().domain(d3.extent(values)).range([rowH - m.bottom, m.top])
      g.append('text').attr('class', 'label').attr('x', 8).attr('y', 12).text(p.name)
      g.append('line').attr('x1', 8).attr('x2', width - 8).attr('y1', rowH - 1).attr('y2', rowH - 1).attr('stroke', 'var(--grid)')
      for (const kde of p.kde) g.append('path').attr('fill', 'none').attr('stroke', 'var(--series-1)').attr('stroke-opacity', 0.55).attr('stroke-width', 1.5)
        .attr('d', d3.line().x((_, i) => x(p.grid[i])).y((v) => yk(v))(kde))
      for (const c of p.draws) g.append('path').attr('fill', 'none').attr('stroke', 'var(--series-1)').attr('stroke-opacity', 0.45).attr('stroke-width', 1)
        .attr('d', d3.line().x((_, i) => xt(i)).y((v) => yt(v))(c))
      const sorted = values.slice().sort(d3.ascending)
      const q = (f) => compact(d3.quantileSorted(sorted, f))
      g.append('rect').attr('class', 'hit').attr('x', 0).attr('y', 0).attr('width', width).attr('height', rowH)
        .on('pointermove', (evt) => {
          const [sx, sy] = d3.pointer(evt, svg.node())
          tip.show(sx, sy - 10, `${p.name}: median ${q(0.5)} [${q(0.05)}, ${q(0.95)}] · ${p.draws.length} chains × ${n} draws`)
        })
        .on('pointerleave', () => tip.hide())
    })
  },

  // Small multiples, one per scalar: each chain's histogram of the ranks of its draws among all
  // chains' (one row per chain). Flat at the dashed line when the chains agree.
  rank(svg, data, width, tip) {
    const { cols, w } = multiples(data.panels.length, width, 220)
    const chains = data.panels[0]?.counts.length ?? 0
    const rowH = 22, head = 24, ph = 22 + chains * rowH + 10
    const h = head + Math.ceil(data.panels.length / cols) * ph
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h)
    legend(svg, [{ label: 'ranks, one row per chain', mark: 'bar' }, { label: 'uniform (chains agree)', mark: 'dash', color: 'var(--ink)' }], 8, 12)
    const top = 2 * data.expected
    data.panels.forEach((p, k) => {
      const g = svg.append('g').attr('transform', `translate(${(k % cols) * w},${head + Math.floor(k / cols) * ph})`)
      g.append('text').attr('class', 'label').attr('x', 10).attr('y', 14).text(p.name)
      const bins = p.counts[0].length
      const x = d3.scaleBand().domain(d3.range(bins)).range([10, w - 10]).padding(0.1)
      p.counts.forEach((row, c) => {
        const y0 = 22 + (c + 1) * rowH
        const y = d3.scaleLinear().domain([0, top]).range([0, rowH - 7]).clamp(true) // a gap between chains
        g.selectAll(null).data(row).join('rect').attr('fill', 'var(--series-1)').attr('x', (_, i) => x(i)).attr('width', x.bandwidth())
          .attr('y', (v) => y0 - y(v)).attr('height', (v) => y(v))
        g.append('line').attr('x1', 10).attr('x2', w - 10).attr('y1', y0 - y(data.expected)).attr('y2', y0 - y(data.expected))
          .attr('stroke', 'var(--ink)').attr('stroke-width', 1).attr('stroke-dasharray', '3 3')
        g.append('rect').attr('class', 'hit').attr('x', 10).attr('y', y0 - rowH).attr('width', w - 20).attr('height', rowH)
          .on('pointermove', (evt) => {
            const [sx, sy] = d3.pointer(evt, svg.node())
            const [gx] = d3.pointer(evt, g.node())
            const i = Math.max(0, Math.min(bins - 1, Math.floor(((gx - 10) / (w - 20)) * bins)))
            tip.show(sx, sy - 10, `${p.name} · chain ${c + 1} · rank bin ${i + 1}: ${row[i]} draws (uniform: ${compact(data.expected)})`)
          })
          .on('pointerleave', () => tip.hide())
      })
    })
  },
}

// Vertical crosshair over a curve's grid with a tooltip.
const crosshair = (svg, x, grid, m, h, tip, text, ty) => {
  const cross = svg.append('line').attr('class', 'cross').attr('y1', m.top).attr('y2', h - m.bottom).attr('visibility', 'hidden')
  svg.append('rect').attr('class', 'hit').attr('x', m.left).attr('y', m.top).attr('width', x.range()[1] - m.left).attr('height', h - m.top - m.bottom)
    .on('pointermove', (evt) => {
      const [px] = d3.pointer(evt, svg.node())
      const i = d3.minIndex(grid, (v) => Math.abs(x(v) - px))
      cross.attr('x1', x(grid[i])).attr('x2', x(grid[i])).attr('visibility', 'visible')
      tip.show(x(grid[i]), ty(i) - 6, text(i))
    })
    .on('pointerleave', () => { cross.attr('visibility', 'hidden'); tip.hide() })
}

const figureData = new Map() // src -> Promise of data: pins and slides share one fetch
rocket('figure-chart', {
  mode: 'open',
  props: ({ string }) => ({ src: string.default(''), label: string.default('figure') }),
  renderOnPropChange: false,
  render: ({ html }) => html`<style>${FIG_STYLE}</style><svg></svg><div class="tip" hidden></div>`,
  onFirstRender: ({ host, props, observeProps, cleanup }) => {
    const root = host.shadowRoot
    const svg = d3.select(root.querySelector('svg'))
    const tipEl = root.querySelector('.tip')
    const tip = {
      show(x, y, text) { tipEl.textContent = text; tipEl.style.left = `${x}px`; tipEl.style.top = `${y}px`; tipEl.hidden = false },
      hide() { tipEl.hidden = true },
    }
    let data = null
    let width = 0
    const draw = () => {
      width = host.clientWidth || width
      if (!data || !width) return
      svg.selectAll('*').remove()
      svg.attr('role', 'img').attr('aria-label', props.label)
      const fn = DRAW[data.chart]
      if (fn) fn(svg, data, width, tip)
      else root.querySelector('svg').insertAdjacentHTML('afterend', `<p class="err">No drawing for "${data.chart}".</p>`)
    }
    const load = async () => {
      if (!props.src) return
      if (!figureData.has(props.src)) figureData.set(props.src, fetch(props.src).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`)))))
      try {
        data = await figureData.get(props.src)
        draw()
      } catch (e) {
        figureData.delete(props.src)
        svg.selectAll('*').remove()
        svg.attr('height', 40).append('text').attr('x', 0).attr('y', 20).text(`Could not load this figure (${e.message}); a newer render may have replaced it.`)
      }
    }
    observeProps(load)
    const ro = new ResizeObserver(() => { if (host.clientWidth !== width) draw() })
    ro.observe(host)
    cleanup(() => ro.disconnect())
    load()
  },
})

// Save a figure-chart as PNG: copy the computed colors onto a clone of its SVG (the page's
// CSS variables don't travel), paint it on the page background at 2x, download.
window.saveFigure = async (host, filename) => {
  const svg = host?.shadowRoot?.querySelector('svg')
  if (!svg) return
  const clone = svg.cloneNode(true)
  const props = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-opacity', 'fill-opacity', 'opacity', 'font-size', 'font-family', 'font-weight', 'visibility']
  const from = [svg, ...svg.querySelectorAll('*')]
  const to = [clone, ...clone.querySelectorAll('*')]
  from.forEach((el, i) => {
    const cs = getComputedStyle(el)
    to[i].setAttribute('style', props.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(';'))
  })
  clone.querySelectorAll('.hit, .cross').forEach((el) => el.remove())
  const { width, height } = svg.getBoundingClientRect()
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', width)
  clone.setAttribute('height', height)
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' }))
  const img = new Image()
  await new Promise((ok, fail) => { img.onload = ok; img.onerror = fail; img.src = url })
  const canvas = document.createElement('canvas')
  canvas.width = width * 2
  canvas.height = height * 2
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = getComputedStyle(document.body).backgroundColor
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.scale(2, 2)
  ctx.drawImage(img, 0, 0, width, height)
  URL.revokeObjectURL(url)
  canvas.toBlob((blob) => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = filename
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  }, 'image/png')
}
