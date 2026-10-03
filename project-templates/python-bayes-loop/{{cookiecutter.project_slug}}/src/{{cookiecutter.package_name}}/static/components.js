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
// points: [[i, q05, q50, q95, truth], ...]. yMin/yMax shared across facets.
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
    const m = { top: 20, right: 8, bottom: 18, left: 36 }
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h).attr('role', 'img').attr('aria-label', `${props.label} across fits`)
    const x = d3.scaleLinear().domain(d3.extent(pts, (p) => p.i)).range([m.left, width - m.right])
    const yd = props.yMin || props.yMax ? [props.yMin, props.yMax] : [d3.min(pts, (p) => Math.min(p.lo, p.truth ?? p.lo)), d3.max(pts, (p) => Math.max(p.hi, p.truth ?? p.hi))]
    const y = d3.scaleLinear().domain(yd).nice(3).range([h - m.bottom, m.top])

    svg.selectAll('text.title').data([0]).join('text').attr('class', 'title label').attr('x', m.left).attr('y', 12).text(props.label)
    svg.selectAll('g.grid').data([0]).join('g').attr('class', 'grid').attr('transform', `translate(${m.left},0)`)
      .call(d3.axisLeft(y).ticks(3).tickSize(-(width - m.left - m.right)).tickFormat(compact))
      .call((g) => g.select('.domain').remove())
      .call((g) => g.selectAll('.tick line').classed('zero', (d) => d === 0))

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
        tooltip.show(x(p.i), y(p.hi), `fit ${p.i + 1}: ${compact(p.mid)} [${compact(p.lo)}, ${compact(p.hi)}]${truth}`)
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
