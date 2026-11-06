// d3 charts as Datastar Rocket web components.
//
// The server stays in charge: it renders each chart as a bare custom element
// whose attributes carry the data, e.g.
//
//   <chart-bars id="events-per-day" series='[["2026-10-01",14012],...]'>
//
// and later morphs change those attributes. Rocket decodes each attribute
// through its prop codec and calls observeProps, and d3 redraws with a
// transition. Components render into an open shadow root, so the page morph
// never touches what d3 drew. Chart data never goes into signals.
//
// The rules that make this work (see the datastar skill):
//   - mode: 'open'. In light mode every morph would erase the SVG.
//   - renderOnPropChange: false. Prop changes redraw; they don't re-render.
//   - An id on every host, so the morph keeps the same element.

import { rocket } from 'datastar'
import * as d3 from 'd3'

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
const duration = () => (reduceMotion.matches ? 0 : 300)
const compact = d3.format('~s')
const commas = d3.format(',')

// Colors come from the page's CSS custom properties, which inherit through
// the shadow boundary, so the theme toggle restyles charts too.
const STYLE = `
  :host { display: block; position: relative; }
  svg { display: block; width: 100%; overflow: visible; }
  text { font: 11px system-ui, sans-serif; fill: var(--color-text-muted); }
  .grid line { stroke: var(--color-border); }
  .base { stroke: var(--color-text-muted); }
  .bar { fill: var(--color-primary); }
  .bar.dim { opacity: .45; }
  .hit { fill: transparent; }
  .tip { position: absolute; pointer-events: none; white-space: nowrap; z-index: 1;
         font: 13px/1.3 system-ui, sans-serif; padding: .3rem .5rem; border-radius: 6px;
         color: var(--color-text); background: var(--color-surface);
         border: 1px solid var(--color-border); box-shadow: var(--shadow);
         transform: translate(-50%, calc(-100% - 8px)); }
  .tip[hidden] { display: none; }
`

// Wires a component up: a shadow root with an <svg> and a tooltip, a redraw
// on data props and on resize. `draw(ctx)` owns everything inside the svg.
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
        hide() {
          tip.hidden = true
        },
      }
      let width = 0
      const redraw = (animate) => {
        width = host.clientWidth || width
        if (width) draw({ svg, props, width, tooltip, t: animate ? duration() : 0 })
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

// Vertical bars: one series over an ordinal axis, e.g. events per day.
chart('chart-bars', {
  props: ({ json, string, number }) => ({
    series: json.default(() => []),
    label: string.default('bar chart'),
    height: number.default(220),
  }),
  draw: ({ svg, props, width, tooltip, t }) => {
    const data = props.series.map(([k, v]) => ({ k: String(k), v: +v }))
    const h = props.height
    const m = { top: 12, right: 8, bottom: 24, left: 44 }
    svg.attr('viewBox', `0 0 ${width} ${h}`).attr('height', h)
      .attr('role', 'img').attr('aria-label', props.label)

    const x = d3.scaleBand().domain(data.map((d) => d.k)).range([m.left, width - m.right]).paddingInner(0.1)
    const y = d3.scaleLinear().domain([0, d3.max(data, (d) => d.v) || 1]).nice(4).range([h - m.bottom, m.top])

    svg.selectAll('g.grid').data([0]).join('g').attr('class', 'grid')
      .attr('transform', `translate(${m.left},0)`)
      .transition().duration(t)
      .call(d3.axisLeft(y).ticks(4).tickSize(-(width - m.left - m.right)).tickFormat(compact))
      .call((g) => g.select('.domain').remove())

    // Label every Nth category so the axis never crowds.
    const every = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(width / 90))))
    svg.selectAll('g.x').data([0]).join('g').attr('class', 'x')
      .attr('transform', `translate(0,${h - m.bottom})`)
      .call(d3.axisBottom(x).tickSize(0).tickPadding(8).tickValues(data.filter((_, i) => i % every === 0).map((d) => d.k)))
      .call((g) => g.select('.domain').remove())

    svg.selectAll('rect.bar').data(data, (d) => d.k)
      .join(
        (enter) => enter.append('rect').attr('class', 'bar').attr('x', (d) => x(d.k)).attr('y', y(0)).attr('height', 0),
        (update) => update,
        (exit) => exit.transition().duration(t).attr('opacity', 0).remove(),
      )
      .transition().duration(t)
      .attr('x', (d) => x(d.k)).attr('width', x.bandwidth())
      .attr('y', (d) => y(d.v)).attr('height', (d) => y(0) - y(d.v))

    svg.selectAll('line.base').data([0]).join('line').attr('class', 'base')
      .attr('x1', m.left).attr('x2', width - m.right).attr('y1', y(0)).attr('y2', y(0))

    // Hit targets span the full column, larger than the mark.
    svg.selectAll('rect.hit').data(data, (d) => d.k).join('rect').attr('class', 'hit')
      .attr('x', (d) => x(d.k)).attr('width', x.bandwidth())
      .attr('y', m.top).attr('height', h - m.top - m.bottom)
      .on('pointerenter pointermove', (_, d) => {
        svg.selectAll('rect.bar').classed('dim', (b) => b.k !== d.k)
        tooltip.show(x(d.k) + x.bandwidth() / 2, y(d.v), `${d.k}: ${commas(d.v)}`)
      })
      .on('pointerleave', () => {
        svg.selectAll('rect.bar').classed('dim', false)
        tooltip.hide()
      })
  },
})
