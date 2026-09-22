'use strict';
const regions = new Map([...document.querySelectorAll('[data-region]')].map(node => [node.dataset.region, node]));
const timers = new Map();
let run = null, sequence = 0, connected = false;
const $ = id => document.getElementById(id);
const mobile = new Map();
for (const system of ['one', 'two']) {
  const list = document.createElement('div'); list.className = 'command-list';
  for (const node of document.querySelectorAll(`.${system} .region`)) {
    const label = document.createElement('span'); label.textContent = node.querySelector('text').textContent;
    list.appendChild(label); mobile.set(node.dataset.region, label);
  }
  $('mobile-commands').appendChild(list);
}
function fire(name) {
  const node = regions.get(name); if (!node) return;
  node.classList.add('active'); mobile.get(name)?.classList.add('active');
  clearTimeout(timers.get(name));
  timers.set(name, setTimeout(() => {node.classList.remove('active'); mobile.get(name)?.classList.remove('active');}, 850));
}
function clearActivity() {
  for (const timer of timers.values()) clearTimeout(timer);
  for (const [name, node] of regions) { node.classList.remove('active', 'thinking'); mobile.get(name)?.classList.remove('active'); }
  $('bridge-path').classList.remove('active');
}
function render(state) {
  const active = ['live', 'shadow', 'guided'].includes(state.phase);
  const labels = {live:'Live', guided:'Guided', shadow:'Observing only', warming:'Warming up', stopped:'Paused', failed:'Stopped', offline:'Offline'};
  $('connection').classList.toggle('live', active);
  $('connection').querySelector('span').textContent = labels[state.phase] || 'Offline';
  if (state.run !== run) {clearActivity(); run = state.run; sequence = 0;}
  if (!active) clearActivity();
  for (const event of state.events || []) {
    if (event.id > sequence && active && Date.now()/1000 - event.at < 1.8) {
      for (const region of event.regions) fire(region);
      if (event.system === 2 && event.regions.includes('plan') && !state.thinking) {
        $('bridge-path').classList.add('active');
        setTimeout(() => $('bridge-path').classList.remove('active'), 850);
      }
      if (event.regions.some(x => x !== 'see')) $('activity').textContent = event.detail || 'Observing';
    }
  }
  sequence = Math.max(sequence, state.sequence || 0);
  const moving = active && state.moving && Date.now()/1000 - state.body_at < 1;
  const talking = active && Date.now()/1000 < state.talk_until;
  regions.get('move').classList.toggle('sustained', !!moving);
  regions.get('talk').classList.toggle('sustained', !!talking);
  mobile.get('move').classList.toggle('active', !!moving);
  mobile.get('talk').classList.toggle('active', !!talking);
  regions.get('plan').classList.toggle('thinking', active && !!state.thinking);
  $('s1-status').textContent = state.phase === 'guided' ? 'Local controls' : !active ? 'Waiting' : state.perception_ms == null ? 'Observing' : `${state.perception_ms} ms`;
  $('s2-status').textContent = state.phase === 'guided' ? 'Guided speech' : state.shadow ? 'Idle' : !active ? 'Waiting' : state.thinking ? 'Thinking' : state.planning_ms == null ? 'Ready' : `${(state.planning_ms/1000).toFixed(1)} s`;
  $('objective').textContent = state.objective || (active ? (state.shadow ? 'Watching the world' : 'Considering what comes next') : 'Waiting for activity');
  $('speech').textContent = state.speech ? `“${state.speech}”` : '';
  $('freshness').textContent = active && state.frame_age_ms != null ? `View ${state.frame_age_ms} ms old` : '';
  if (!active) $('activity').textContent = state.phase === 'warming' ? 'Loading OpenJev' : (state.activity || 'No active run');
}
async function poll() {
  try {
    const response = await fetch('/api/state', {cache:'no-store', signal:AbortSignal.timeout(2000)});
    if (!response.ok) throw new Error('Disconnected');
    render(await response.json()); connected = true;
  } catch (_) {
    if (connected || run === null) render({phase:'offline', events:[], sequence, run});
    connected = false;
  } finally {setTimeout(poll, document.hidden ? 1500 : 250);}
}
poll();
