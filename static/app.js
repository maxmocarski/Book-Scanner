'use strict';

const $ = id => document.getElementById(id);
const state = {
  token: sessionStorage.getItem('bookbridge-token'),
  me: null,
  tab: 'scan',
  register: false,
  photos: {},
  view: 'front',
  stream: null,
  scans: [],
  books: [],
  ownBooks: [],
  friends: [],
  trades: [],
  owner: '',
  review: null,
  book: null,
  wanted: null,
  photoCache: new Map(),
  poll: null,
  epoch: 0,
  busyUpload: false
};

const views = { front: 'Front', spine: 'Spine', back: 'Back' };

const e = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

function button(text, cls, action) {
  const n = e('button', cls, text);
  n.type = 'button';
  n.addEventListener('click', () => Promise.resolve().then(action).catch(err => toast(err.message)));
  return n;
}

function toast(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $('toast').hidden = true, 5000);
}

function errorText(detail) {
  if (Array.isArray(detail)) return detail.map(x => (x.loc || []).slice(1).join(' ') + ': ' + x.msg).join('. ');
  return typeof detail === 'string' ? detail : 'Request failed. Please try again.';
}

async function api(path, options = {}) {
  const authenticated = options.authenticated !== false;
  const epoch = state.epoch;
  const headers = new Headers(options.headers || {});

  if (authenticated && state.token) headers.set('Authorization', 'Bearer ' + state.token);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
    options.body = JSON.stringify(options.body);
  }

  let response;
  try {
    response = await fetch(path, { ...options, headers, cache: 'no-store' });
  } catch {
    throw new Error('Could not reach the server. Check your connection.');
  }

  if (authenticated && epoch !== state.epoch) throw new Error('Your sign-in changed. Try again.');

  if (!response.ok) {
    let detail;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = null;
    }
    if (authenticated && (response.status === 401 || response.status === 403 && detail === 'Not authenticated')) {
      clearSession();
      $('auth-error').textContent = 'Please sign in again.';
    }
    throw new Error(errorText(detail));
  }

  if (response.status === 204) return null;
  return options.responseType === 'blob' ? response.blob() : response.json();
}

async function formAction(form, action, errorId) {
  const controls = [...form.querySelectorAll('button')];
  const disabledBefore = controls.map(b => b.disabled);
  controls.forEach(b => b.disabled = true);
  if (errorId) $(errorId).textContent = '';
  try {
    await action();
  } catch (err) {
    if (errorId) $(errorId).textContent = err.message;
    else toast(err.message);
  } finally {
    controls.forEach((b, i) => b.disabled = disabledBefore[i]);
  }
}

function closeDialogs() {
  document.querySelectorAll('dialog[open]').forEach(d => d.close());
}

function stopCamera() {
  if (state.stream) state.stream.getTracks().forEach(t => t.stop());
  state.stream = null;
  $('camera-video').srcObject = null;
  $('camera-video').closest('.camera').classList.remove('live');
  $('camera-placeholder').hidden = false;
  $('camera-close').hidden = true;

  $('camera-controls').hidden = true;
  $('shutter').disabled = true;
}

function clearPhotos() {
  Object.values(state.photos).forEach(p => URL.revokeObjectURL(p.url));
  state.photos = {};
  state.view = 'front';
  renderPhotos();
}

function clearSession() {
  state.epoch++;
  clearInterval(state.poll);
  state.poll = null;
  stopCamera();
  clearPhotos();
  $('scan-shelf').value = '';
  closeDialogs();
  state.photoCache.forEach(p => {
    if (p.url) URL.revokeObjectURL(p.url);
  });
  state.photoCache.clear();
  state.token = null;
  state.me = null;
  state.scans = [];
  state.books = [];
  state.ownBooks = [];
  state.friends = [];
  state.trades = [];
  state.owner = '';
  sessionStorage.removeItem('bookbridge-token');
  $('workspace').hidden = true;
  $('account').hidden = true;
  $('auth').hidden = false;
  $('auth-password').value = '';
  $('invite-code').value = '';
  $('invite-result').hidden = true;
  $('scan-feedback').textContent = '';
  $('queue-list').replaceChildren();
  $('book-grid').replaceChildren();
  $('friend-list').replaceChildren();
  $('trade-list').replaceChildren();
  clearCommunity();
  resetPublic();
  state.tab='auth';
  $('guest-signin').classList.add('active');
  $('guest-signin').setAttribute('aria-pressed','true');
  $('page-public').hidden=true;
  $('guest-navigation').hidden=false;
}

async function startSession() {
  state.me = await api('/me');
  applySettings();
  $('auth').hidden = true;
  $('guest-navigation').hidden=true;
  $('workspace').hidden = false;
  $('account').hidden = false;
  $('auth-password').value = '';
  state.owner = '';
  navigate('scan');
  await refreshAll();
  if (!state.me.profile_complete) showProfileSetup();
  clearInterval(state.poll);
  state.poll = setInterval(() => {
    if (state.me && !document.hidden) refreshScans().catch(() => {});
  }, 2500);
}

function navigate(tab) {
  closeSections();
  state.tab = tab;
  if (!state.me) $('auth').hidden=tab==='public';
  $('guest-signin').classList.toggle('active',tab==='auth');
  $('guest-signin').setAttribute('aria-pressed',String(tab==='auth'));
  if (tab==='public') refreshPublic().catch(err=>publicError(err));
  window.scrollTo({top:0,behavior:'instant'});
  if (tab !== 'scan') stopCamera();
  document.querySelectorAll('.page').forEach(p => p.hidden = p.id !== 'page-' + tab);
  document.querySelectorAll('[data-tab]').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab);
    b.setAttribute('aria-pressed', String(b.dataset.tab === tab));
  });
  if (tab === 'queue') renderQueue();
  if (tab === 'library') renderLibrary();
  if (tab === 'friends') {
    renderFriends();
    renderTrades();
  }
  if (tab === 'trades') renderTrades();
  if (state.me && !['scan','public'].includes(tab)) refreshAll().catch(err => toast(err.message));
}

async function refreshAll() {
  const epoch = state.epoch, serial = (state.refreshSerial || 0) + 1, owner = state.owner;
  state.refreshSerial = serial;

  const requests = [api('/scans?limit=500'), api('/books'), api('/friends'), api('/trades')];
  if (owner) {
    requests.push(api('/books?' + (owner.startsWith('lib:') ? 'library_id=' + encodeURIComponent(owner.slice(4)) : 'owner_id=' + encodeURIComponent(owner))).catch(err => {
      if (err.message === 'Not found.' || err.message === 'Library not found or access removed.') return null;
      throw err;
    }));
  }

  const [scans, books, friends, trades, friendBooks] = await Promise.all(requests);
  if (epoch !== state.epoch || serial !== state.refreshSerial || owner !== state.owner) return;

  state.scans = scans;
  state.ownBooks = books;
  state.friends = friends;
  state.trades = trades;
  if (owner && (!friendBooks || (!owner.startsWith('lib:') && !friends.some(f => f.id === owner)))) state.owner = '';

  state.books = state.owner ? friendBooks : books;
  state.libraryLoading = false;
  await refreshCommunity();
  if (epoch !== state.epoch || serial !== state.refreshSerial) return;
  renderOwnerOptions();
  updateQueueBadge();

  if (state.tab === 'queue') renderQueue();
  if (state.tab === 'trades') renderTrades();
  if (state.tab === 'library') renderLibrary();
  if (state.tab === 'friends') {
    renderFriends();
    renderTrades();
  }
}

async function refreshScans() {
  const scans = await api('/scans?limit=500');
  state.scans = scans;
  updateQueueBadge();
  if (state.tab === 'queue') renderQueue();
}

function updateQueueBadge() {
  const count = state.scans.length;
  $('queue-count').textContent = count;
  $('queue-count').hidden = !count;
}

function empty(container, title, description, action) {
  const box = e('div', 'empty');
  box.append(e('h2', '', title), e('p', '', description));
  if (action) box.append(action);
  container.append(box);
}

async function loadImage(img, path) {
  const epoch = state.epoch;
  try {
    let entry = state.photoCache.get(path);
    if (!entry) {
      entry = {};
      entry.promise = (async () => {
        const response = await fetch(path, { headers: { Authorization: 'Bearer ' + state.token }, cache: 'no-store' });
        if (!response.ok) throw new Error('Photo unavailable');
        const blob = await response.blob();
        if (epoch !== state.epoch) throw new Error('Session changed');
        entry.url = URL.createObjectURL(blob);
        return entry.url;
      })();
      state.photoCache.set(path, entry);
    }
    img.src = await entry.promise;
  } catch {
    state.photoCache.delete(path);
    img.alt = 'Photo unavailable';
  }
}

const imageObserver = new IntersectionObserver(items => {
  for (const item of items) {
    if (item.isIntersecting) {
      imageObserver.unobserve(item.target);
      loadImage(item.target, item.target.dataset.photo);
    }
  }
}, { rootMargin: '150px' });

function image(path, cls, alt) {
  const img = e('img', cls);
  img.alt = alt;
  img.dataset.photo = path;
  imageObserver.observe(img);
  return img;
}

function renderPhotos() {
  const root = $('photo-slots');
  root.replaceChildren();

  for (const view of Object.keys(views)) {
    const wrap = e('div', 'photo-slot' + (view === state.view ? ' active' : ''));
    const choice = button('', 'photo-choice', () => {
      state.view = view;
      renderPhotos();
    });

    choice.setAttribute('aria-label', 'Select ' + view + ' photo');
    const photo = state.photos[view];

    if (photo) {
      const img = e('img');
      img.src = photo.url;
      img.alt = view + ' preview';
      choice.append(img);
    } else {
      choice.append(e('span', 'plus', '+'));
    }

    choice.append(e('span', '', views[view] + (view === 'front' ? ' · required' : '')));
    wrap.append(choice);

    if (photo) {
      const remove = button('×', 'remove-photo', () => {
        URL.revokeObjectURL(photo.url);
        delete state.photos[view];
        renderPhotos();
      });
      remove.setAttribute('aria-label', 'Remove ' + view + ' photo');
      wrap.append(remove);
    }
    root.append(wrap);
  }

  $('upload-photo').textContent = 'Upload ' + state.view + ' photo';
  $('camera-view').textContent = state.view === 'front' ? 'Front cover' : views[state.view];
  $('queue-book').disabled = !state.photos.front || state.busyUpload;
}

async function setPhoto(file, view) {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Please use a JPG, PNG or WebP photo.');
  if (file.size > 10 * 1024 * 1024) throw new Error('Choose a photo smaller than 10 MB.');

  const epoch = state.epoch;
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error('This photo could not be opened. Try another image.');
  }

  const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();

  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .88));
  if (!blob) throw new Error('This photo could not be prepared.');
  if (epoch !== state.epoch) return;

  if (state.photos[view]) URL.revokeObjectURL(state.photos[view].url);
  state.photos[view] = { blob, url: URL.createObjectURL(blob) };
  state.view = Object.keys(views).find(v => !state.photos[v]) || view;
  renderPhotos();
}

async function openCamera() {
  const epoch = state.epoch;
  $('camera-open').disabled = true;
  try {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      throw new Error('Camera access needs HTTPS or localhost. You can still upload a photo.');
    }
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    if (epoch !== state.epoch || state.tab !== 'scan') {
      stream.getTracks().forEach(t => t.stop());
      return;
    }
    stopCamera();
    state.stream = stream;
    $('camera-video').srcObject = stream;
    await $('camera-video').play();
    $('camera-placeholder').hidden = true;
    $('camera-close').hidden = false;

    $('camera-controls').hidden = false;
    $('camera-video').closest('.camera').classList.add('live');
    $('shutter').disabled = false;
  } catch (err) {
    stopCamera();
    toast(err.message === 'Permission denied' ? 'Camera permission denied. Allow access or upload a photo.' : err.message);
  } finally {
    $('camera-open').disabled = false;
  }
}

async function capturePhoto() {
  const video = $('camera-video');
  if (!video.videoWidth) return;
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .9));
  if (blob) await setPhoto(new File([blob], 'capture.jpg', { type: 'image/jpeg' }), state.view);
}

function renderQueue() {
  const root = $('queue-list');
  root.replaceChildren();

  const queueScans = state.scans.filter(s => (s.library_id || '') === $('queue-library').value);
  if (!queueScans.length) {
    empty(root, 'A clear queue.', 'Photograph a book to get started.', button('Scan a book', 'primary', () => navigate('scan')));
    return;
  }

  for (const scan of [...queueScans].sort((a, b) => {
    const order = { ready: 0, failed: 1, identifying: 2, enriching: 2, queued: 3 };
    return order[a.status] - order[b.status] || a.created - b.created;
  })) {
    const row = e('article', 'queue-card');
    if (scan.images[0]) row.append(image(scan.images[0].url, 'queue-cover', 'Scanned front cover'));

    const info = e('div', 'queue-info');
    info.append(e('h3', '', scan.metadata.title || scan.original_metadata.title || 'Book scan'));

    const descriptions = {
      queued: 'Waiting' + (scan.queue_position ? ' · position ' + scan.queue_position : ''),
      identifying: 'Reading your photos…',
      enriching: 'Checking the text…',
      ready: scan.metadata.author || 'Ready for your review',
      failed: scan.error || 'Scan failed. You can retry.'
    };
    info.append(e('p', 'muted', descriptions[scan.status]));
    if (scan.shelf) info.append(e('p','small muted','Shelf: '+(scan.shelf_label || scan.shelf)));
    if (scan.duplicate) info.append(e('p','duplicate-warning',duplicateMessage(scan.duplicate)));

    const badge = e('span', 'badge ' + scan.status, {
      ready: 'READY TO REVIEW',
      failed: 'NEEDS ATTENTION',
      queued: 'QUEUED',
      identifying: 'SCANNING',
      enriching: 'FINISHING'
    }[scan.status]);

    if (['identifying', 'enriching'].includes(scan.status)) badge.prepend(e('span', 'spinner'));
    info.append(badge);
    row.append(info);

    const actions = e('div', 'queue-actions');
    if (scan.status === 'ready') actions.append(button('Review', 'primary', () => openReview(scan)));
    if (scan.status === 'failed') actions.append(button('Retry', 'secondary', async () => {
      await api('/scans/' + scan.id + '/retry', { method: 'POST' });
      await refreshScans();
      toast('Book requeued.');
    }));

    actions.append(button('Discard', 'text-button danger', async () => {
      if (!confirm('Discard this scan and its photos?')) return;
      await api('/scans/' + scan.id, { method: 'DELETE' });
      await refreshScans();
      toast('Scan discarded.');
    }));

    row.append(actions);
    root.append(row);
  }
}

function photoStrip(root, photos) {
  root.replaceChildren();
  for (const photo of photos) {
    const figure = e('figure');
    figure.append(image(photo.url, '', photo.view + ' of the book'), e('figcaption', '', photo.view));
    root.append(figure);
  }
}

function openReview(scan) {
  state.review = scan;
  $('review-book-title').value = scan.metadata.title || '';
  $('review-author').value = scan.metadata.author || '';
  $('review-isbn').value = scan.metadata.isbn || '';
  $('review-shelf').value = scan.shelf || '';
  $('review-shelf-location').textContent = scan.shelf_label ? 'Current location: '+scan.shelf_label : '';
  $('review-available').checked = false;
  $('review-error').textContent = '';
  photoStrip($('review-photos'), scan.images);

  const notes = $('review-notes');
  notes.replaceChildren(e('p', '', 'Check these fields against your photos before saving.'));

  if (scan.duplicate) notes.append(e('p','duplicate-warning',duplicateMessage(scan.duplicate)));
  if (scan.warnings.length) {
    const list = e('ul');
    scan.warnings.forEach(w => list.append(e('li', '', w)));
    notes.append(list);
  }

  if (scan.corrections.length) {
    const detail = e('details');
    detail.append(e('summary', '', 'Text corrections'));
    for (const change of scan.corrections) {
      detail.append(e('p', '', change.field + ': ' + (change.before || 'blank') + ' → ' + (change.after || 'blank')));
    }
    notes.append(detail);
  }

  if (scan.lookup_suggestion) {
    const suggested = scan.lookup_suggestion.metadata;
    const detail = e('div');
    detail.append(
      e('p', '', 'Lookup suggestion · check the edition'),
      e('p', '', [suggested.title, suggested.author, suggested.isbn].filter(Boolean).join(' · ')),
      button('Use these suggested fields', 'secondary', () => {
        if (suggested.title) $('review-book-title').value = suggested.title;
        if (suggested.author) $('review-author').value = suggested.author;
        if (suggested.isbn) $('review-isbn').value = suggested.isbn;
      })
    );
    notes.append(detail);
  }

  if (scan.sources.length) {
    const detail = e('details');
    detail.append(e('summary', '', 'Lookup sources'));
    scan.sources.forEach(s => {
      const p = e('p');
      const a = e('a', '', s.title || 'Book result');
      a.href = s.url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      p.append(a);
      detail.append(p);
    });
    notes.append(detail);
  }

  $('review-dialog').showModal();
}

function reviewedBody(prefix) {
  return {
    title: $(prefix + '-title').value.trim(),
    author: $(prefix === 'review-book' ? 'review-author' : 'book-author').value.trim(),
    isbn: $(prefix === 'review-book' ? 'review-isbn' : 'book-isbn').value.trim() || null,
    shelf: $(prefix === 'review-book' ? 'review-shelf' : 'book-shelf').value.trim(),
    available: $(prefix === 'review-book' ? 'review-available' : 'book-available').checked
  };
}

function renderOwnerOptions() {

  const select = $('library-owner');
  select.replaceChildren(new Option('My library', ''));
  state.friends.filter(f => !f.private_library && !state.me.private_library).forEach(f => select.add(new Option((f.display_name || f.username) + "’s library", f.id)));
  (state.libraries || []).forEach(l => select.add(new Option(l.name + ' · shared', 'lib:' + l.id)));
  select.value = state.owner;
}

function reserved(id) {
  return state.trades.some(t => t.status === 'accepted' && (t.wanted === id || t.offered === id));
}

function renderLibrary() {
  $('my-library').hidden = !state.owner;
  $('library-export').hidden = !state.owner.startsWith('lib:');
  const friend = state.friends.find(f => f.id === state.owner);
  const shared = (state.libraries || []).find(l => 'lib:' + l.id === state.owner);
  $('library-title').textContent = shared ? shared.name : friend ? (friend.display_name || friend.username) + "’s library." : 'Your little library.';
  $('library-description').textContent = shared ? 'A shared catalog for your library members.' : friend ? 'A good book might be one swap away.' : 'Books you own, stories you can share.';

  const query = $('library-search').value.toLocaleLowerCase().trim();
  const books = state.books.filter(b => (!$('available-only').checked || b.available && !reserved(b.id)) && [b.title, b.author, b.isbn || '', b.shelf_label || b.shelf || ''].join(' ').toLocaleLowerCase().includes(query));

  $('library-count').textContent = books.length + ' ' + (books.length === 1 ? 'book' : 'books') + (query ? ' found' : ' on the shelf');

  const grid = $('book-grid');
  grid.replaceChildren();
  applyCatalogView(grid);

  if (state.libraryLoading) { grid.append(e('p','muted','Loading this library…')); return; }
  if (!books.length) {
    empty(grid, state.books.length ? 'No matches yet.' : friend ? 'An empty shelf.' : 'Make room for your first book.', state.books.length ? 'Try another title or author.' : friend ? 'Your friend hasn’t added any books yet.' : 'Scan a book and save it here.', !friend && !state.books.length ? button('Scan a book', 'primary', () => { $('scan-library').value = shared?.id || ''; navigate('scan'); }) : null);
    grid.firstChild.style.gridColumn = '1 / -1';
    return;
  }

  const groups = groupCopies(books);
  $('library-count').textContent = groups.length + (groups.length===1?' title':' titles');
  for (const copies of groups) {
    const book=copies[0];
    grid.append(makeBookCard(copies,()=>copies.length>1?openCopies(copies):openBook(book),item=>image(item.image_url,'',item.title+' cover')));
  }
}

function openBook(book) {
  state.book = book;
  const shared = (state.libraries || []).find(l => l.id === book.library_id);
  const own = book.owner === state.me.id || shared?.owner === state.me.id;
  const locked = reserved(book.id);

  $('book-title').value = book.title;
  $('book-author').value = book.author;
  $('book-isbn').value = book.isbn || '';
  $('book-shelf').value = book.shelf || '';
  $('book-shelf-location').textContent = book.shelf_label ? 'Current location: '+book.shelf_label : '';
  $('book-available').checked = Boolean(book.available);

  ['book-title', 'book-author', 'book-isbn', 'book-shelf', 'book-available'].forEach(id => $(id).disabled = !own || locked);
  $('book-own-actions').hidden = !own;
  $('book-own-actions').querySelector('.primary').disabled = locked;
  $('delete-book').disabled = locked;
  $('book-available-label').hidden = !own || Boolean(book.library_id) || state.me.private_library;
  $('reading-open').hidden = book.owner !== state.me.id;
  $('request-swap').hidden = own || !book.available || locked || Boolean(book.library_id) || state.me.private_library;

  $('book-note').textContent = locked ? 'Reserved for an accepted trade. Cancel the trade before editing.' : own ? 'Mark this book available when you’re ready to share it.' : book.available ? 'Your friend is open to trading this book.' : 'This book is not available to trade.';
  $('book-error').textContent = '';

  photoStrip($('book-photos'), book.images);
  $('book-dialog').showModal();
}

function renderFriends() {
  const root = $('friend-list');
  root.replaceChildren();

  if (!state.friends.length) {
    root.append(e('p', 'muted small', 'No connections yet. Share an invitation with someone you know.'));
    return;
  }

  for (const friend of state.friends) {
    const card = e('div', 'friend-card');
    card.append(
      e('span', 'friend-avatar', friend.username[0].toUpperCase()),
      e('span', 'friend-name', friend.display_name || friend.username),
      button('Browse books', 'text-button', async () => {
        if (friend.private_library || state.me.private_library) { toast('This personal library is private.'); return; }
        openLibrary(friend.id);
      }),
      button('Remove', 'text-button danger', async () => {
        if (!confirm('Remove ' + friend.username + '? This also cancels open trades with them.')) return;
        await api('/friends/' + friend.id, { method: 'DELETE' });
        await refreshAll();
        toast('Connection removed.');
      })
    );
    root.append(card);
  }
}

function renderTrades() {
  const root = $('trade-list');
  root.replaceChildren();

  if (!state.trades.length) {
    root.append(e('p', 'muted small', 'Browse a friend’s available books to request your first swap.'));
    return;
  }

  for (const trade of state.trades) {
    const sender = trade.sender === state.me.id;
    const name = sender ? trade.recipient_username : trade.sender_username;

    const info = e('div', 'trade-info');
    info.append(
      e('h3', '', (sender ? 'Your request to ' : 'Request from ') + (name || 'a friend')),
      e('p', 'muted', 'Your book: ' + (sender ? trade.offered_title : trade.wanted_title)),
      e('p', 'muted', 'Their book: ' + (sender ? trade.wanted_title : trade.offered_title)),
      e('span', 'badge ' + trade.status, trade.status.toUpperCase())
    );

    const row = e('article', 'trade-card');
    row.append(info);

    const actions = e('div', 'trade-actions');
    const act = async action => {
      await api('/trades/' + trade.id + '/' + action, { method: 'POST' });
      await refreshAll();
      toast(action === 'confirm-handoff' ? 'Handoff confirmation saved.' : 'Trade updated.');
    };

    if (trade.status === 'pending' && !sender) actions.append(button('Accept', 'primary', () => act('accept')));
    if (trade.status === 'accepted') {
      const confirmed = sender ? trade.sender_confirm : trade.recipient_confirm;
      if (confirmed) {
        info.append(e('p', 'muted small', 'You confirmed. Waiting for your friend.'));
      } else {
        actions.append(button('Confirm handoff', 'primary', () => {
          if (confirm('Have you physically exchanged these books? Ownership transfers after both people confirm.')) return act('confirm-handoff');
        }));
      }
    }

    if (['pending', 'accepted'].includes(trade.status)) {
      actions.append(button(trade.status === 'pending' && !sender ? 'Decline' : 'Cancel', 'secondary', () => {
        if (confirm('Cancel this trade?')) return act('cancel');
      }));
    }

    row.append(actions);
    root.append(row);
  }
}

async function openSwap() {
  state.wanted = state.book;
  $('book-dialog').close();
  $('swap-description').textContent = 'Request “' + state.wanted.title + '” and offer one of your books.';
  $('swap-error').textContent = '';

  const select = $('swap-offer');
  select.replaceChildren(new Option('Choose a book', ''));
  state.ownBooks.filter(b => b.available && !reserved(b.id)).forEach(b => select.add(new Option(b.title + ' — ' + b.author, b.id)));

  $('swap-submit').disabled = select.options.length <= 1;
  if (select.options.length <= 1) $('swap-error').textContent = 'Mark one of your books available in My library first.';
  $('swap-dialog').showModal();
}

$('auth-toggle').addEventListener('click', () => {
  state.register = !state.register;
  $('auth-title').textContent = state.register ? 'Start your library' : 'Welcome back';
  $('auth-description').textContent = state.register ? 'Create an account to keep your books together.' : 'Sign in to your personal library.';
  $('auth-submit').textContent = state.register ? 'Create account' : 'Sign in';
  $('auth-toggle').textContent = state.register ? 'Sign in' : 'Create an account';
  $('auth-switch-label').textContent = state.register ? 'Already have an account?' : 'New here?';
  $('auth-password').autocomplete = state.register ? 'new-password' : 'current-password';
  $('auth-error').textContent = '';
});

$('auth-form').addEventListener('submit', event => {
  event.preventDefault();
  formAction(event.currentTarget, async () => {
    const response = await api(state.register ? '/auth/register' : '/auth/login', {
      method: 'POST',
      authenticated: false,
      body: { username: $('auth-name').value.trim(), password: $('auth-password').value, website: $('auth-website').value }
    });
    state.epoch++;
    state.token = response.access_token;
    sessionStorage.setItem('bookbridge-token', state.token);
    await startSession();
  }, 'auth-error');
});

$('logout').addEventListener('click', async () => {
  if (!confirm('Sign out of BookBridge?')) return;
  try {
    await api('/auth/logout', { method: 'POST' });
  } catch (err) {
    if (state.token) {
      toast('Could not sign out on the server. Check your connection and try again.');
      return;
    }
  }
  clearSession();
  toast('Signed out.');
});

document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => b.dataset.tab === 'library' ? openLibrary('') : navigate(b.dataset.tab)));
document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => $(b.dataset.close).close()));

$('camera-open').addEventListener('click', openCamera);
$('camera-close').addEventListener('click', stopCamera);
$('shutter').addEventListener('click', () => capturePhoto().catch(err => toast(err.message)));

$('upload-photo').addEventListener('click', () => {
  $('photo-input').value = '';
  $('photo-input').dataset.view = state.view;
  $('photo-input').click();
});

$('photo-input').addEventListener('change', event => {
  const file = event.target.files[0];
  if (file) setPhoto(file, event.target.dataset.view).catch(err => toast(err.message));
});

$('queue-book').addEventListener('click', async () => {
  if (state.busyUpload || !state.photos.front) return;
  state.busyUpload = true;
  renderPhotos();
  $('queue-book').textContent = 'Uploading…';

  try {
    const form = new FormData();
    for (const view of Object.keys(views)) {
      if (state.photos[view]) form.append(view, state.photos[view].blob, view + '.jpg');
    }
    form.append('shelf', $('scan-shelf').value.trim());
    form.append('enrichment', state.me.secondary_review ? state.me.review_mode : 'off');
    if ($('scan-library').value) form.append('library_id', $('scan-library').value);
    await api('/scans', { method: 'POST', body: form });
    $('queue-library').value = $('scan-library').value;
    clearPhotos();
    $('scan-feedback').textContent = 'Book queued. You’re ready for the next one.';
    await refreshScans();
    toast('Book queued. Review it in Book queue when it’s ready.');
  } catch (err) {
    toast(err.message);
  } finally {
    state.busyUpload = false;
    $('queue-book').textContent = 'Add book to queue →';
    renderPhotos();
  }
});

$('review-form').addEventListener('submit', event => {
  event.preventDefault();
  formAction(event.currentTarget, async () => {
    await api('/scans/' + state.review.id + '/save', { method: 'POST', body: reviewedBody('review-book') });
    $('review-dialog').close();
    await refreshAll();
    toast('Book added to your library.');
  }, 'review-error');
});

$('book-form').addEventListener('submit', event => {
  event.preventDefault();
  if (state.book.owner !== state.me.id && !(state.libraries || []).some(l => l.id === state.book.library_id && l.owner === state.me.id)) return;
  formAction(event.currentTarget, async () => {
    await api('/books/' + state.book.id, { method: 'PATCH', body: reviewedBody('book') });
    $('book-dialog').close();
    await refreshAll();
    toast('Book updated.');
  }, 'book-error');
});

$('delete-book').addEventListener('click', async () => {
  if (!confirm('Remove this book and its photos from your library?')) return;
  try {
    await api('/books/' + state.book.id, { method: 'DELETE' });
    $('book-dialog').close();
    await refreshAll();
    toast('Book removed.');
  } catch (err) {
    $('book-error').textContent = err.message;
  }
});

$('request-swap').addEventListener('click', () => openSwap().catch(err => toast(err.message)));

$('swap-form').addEventListener('submit', event => {
  event.preventDefault();
  formAction(event.currentTarget, async () => {
    await api('/trades', { method: 'POST', body: { wanted_book_id: state.wanted.id, offered_book_id: $('swap-offer').value } });
    $('swap-dialog').close();
    navigate('trades');
    await refreshAll();
    toast('Trade request sent.');
  }, 'swap-error');
});

$('library-owner').addEventListener('change', () => openLibrary($('library-owner').value));
$('my-library').addEventListener('click', () => openLibrary(''));

$('library-search').addEventListener('input', renderLibrary);
$('available-only').addEventListener('change', renderLibrary);

['queue-refresh', 'library-refresh', 'friends-refresh'].forEach(id => $(id).addEventListener('click', () => refreshAll().catch(err => toast(err.message))));

$('create-invite').addEventListener('click', async () => {
  $('create-invite').disabled = true;
  try {
    const invite = await api('/friends/invites', { method: 'POST' });
    $('invite-code').value = invite.code;
    $('invite-result').hidden = false;
  } catch (err) {
    toast(err.message);
  } finally {
    $('create-invite').disabled = false;
  }
});

$('copy-invite').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText($('invite-code').value);
    toast('Invite code copied.');
  } catch {
    $('invite-code').select();
    toast('Select and copy this code to share it.');
  }
});

$('accept-invite-form').addEventListener('submit', event => {
  event.preventDefault();
  formAction(event.currentTarget, async () => {
    await api('/friends/accept', { method: 'POST', body: { code: $('accept-invite-code').value.trim() } });
    $('accept-invite-code').value = '';
    await refreshAll();
    toast('You’re connected. Browse their library below.');
  });
});

document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopCamera();
  else if (state.tab==='public') refreshPublic().catch(err=>publicError(err));
  else if (state.me && !['settings','admin'].includes(state.tab)) refreshAll().catch(() => {});
});

window.addEventListener('pagehide', stopCamera);

renderPhotos();
