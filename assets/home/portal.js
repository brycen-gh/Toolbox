// Render only explicitly published public fields; never interpret them as HTML.
async function loadServices() {
  const cards = document.getElementById('cards');
  try {
    const response = await fetch('services.json', {cache: 'no-store'});
    if (!response.ok) throw new Error('Configuration unavailable');
    const data = await response.json();
    const localNames = ['localhost', 'localhost.', '127.0.0.1', '[::1]', '::1'];
    const browserHost = window.location.hostname;
    const host = data.host === 'auto' || localNames.includes(data.host)
      ? (localNames.includes(browserHost) && data.detected_host ? data.detected_host : browserHost)
      : data.host;
    const items = data.services.map(service => {
      const url = new URL(service.url || `${service.scheme}://${host}:${service.port}${service.path || '/'}`);
      // Explicit localhost site URLs belong to the server, not each student's computer.
      if (localNames.includes(url.hostname)) url.hostname = host;
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Invalid service address');
      const card = document.createElement('article'); card.className = 'card';
      const badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = service.name.slice(0, 2); badge.setAttribute('aria-hidden', 'true');
      const title = document.createElement('h3'); title.textContent = service.name;
      const description = document.createElement('p'); description.textContent = service.description;
      const link = document.createElement('a'); link.href = url.href; link.textContent = `Open ${service.name} ↗`; link.target = '_blank'; link.rel = 'noopener noreferrer';
      const address = document.createElement('small'); address.textContent = url.host;
      card.append(badge, title, description, link, address); return card;
    });
    cards.replaceChildren(...items);
  } catch (error) {
    cards.textContent = 'Service links could not be loaded. Ask your instructor to regenerate Home using Install Home in Toolbox. The help guides below are still available.';
  }
}
loadServices();
