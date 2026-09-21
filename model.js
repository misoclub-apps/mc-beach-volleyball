export const normalize = text => String(text ?? '').normalize('NFKC').replace(/\s/g, '').replaceAll('髙', '高').replaceAll('﨑', '崎').toLowerCase();
export const todayJst = (now = new Date()) => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo' }).format(now);
export const isUpcoming = (event, today = todayJst()) => Boolean(event.endDate && event.endDate >= today && !event.cancelled);
export const appearances = (data, id) => data.events.flatMap(event => event.entries.filter(e => e.playerIds.includes(id)).map(entry => ({ event, entry })));
export function filterPlayers(data, { query = '', gender = '', upcoming = false, favorites = false, saved = [], today = todayJst() } = {}) {
  const q = normalize(query);
  return data.players.filter(p => (!gender || p.gender === gender) && (!favorites || saved.includes(p.id)) &&
    (!q || normalize([p.name, p.roman, ...p.aliases].join(' ')).includes(q)) &&
    (!upcoming || appearances(data, p.id).some(a => isUpcoming(a.event, today) && a.entry.status === 'entered')))
    .sort((a, b) => {
      const count = p => appearances(data, p.id).filter(a => isUpcoming(a.event, today) && a.entry.status === 'entered').length;
      return count(b) - count(a) || a.name.localeCompare(b.name, 'ja');
    });
}
export function filterEvents(data, { query = '', category = '', period = 'upcoming', today = todayJst() } = {}) {
  return data.events.filter(e => (!query || normalize(`${e.name} ${e.venue}`).includes(normalize(query))) &&
    (!category || e.category === category) && (period === 'all' || (period === 'past' ? Boolean(e.endDate && e.endDate < today) : Boolean(e.endDate && e.endDate >= today))));
}
export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export function safeLink(value) { try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) ? escapeHtml(u.href) : '#'; } catch { return '#'; } }
