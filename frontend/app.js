// Straight Library Frontend

const API_BASE = '/api';
const ENTRIES_PER_PAGE = 10;

// State
let entriesPage = 0;
let entriesTotal = 0;
let currentEntryId = null;
let currentEntryMeta = null;
let currentSection = 'shortsummary';
let currentPage = 1;
let currentTotalPages = 0;
let selectedFiles = [];
let filterDebounceTimer = null;
let entriesMap = {};
let searchMode = 'fts'; // 'fts' or 'semantic'

// DOM Elements
const tabs = document.querySelectorAll('.tab');
const tabContents = document.querySelectorAll('.tab-content');
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const uploadForm = document.getElementById('upload-form');
const uploadBtn = document.getElementById('upload-btn');
const uploadStatus = document.getElementById('upload-status');
const entriesCount = document.getElementById('entries-count');
const entriesList = document.getElementById('entries-list');
const entriesPagination = document.getElementById('entries-pagination');
const readPlaceholder = document.getElementById('read-placeholder');
const readContent = document.getElementById('read-content');
const readEntryInfo = document.getElementById('read-entry-info');
const pageContentEl = document.getElementById('page-content');
const pagePagination = document.getElementById('page-pagination');
const sectionBtns = document.querySelectorAll('.section-btn');
const filterInputs = {
    title: document.getElementById('filter-title'),
    author: document.getElementById('filter-author'),
    genre: document.getElementById('filter-genre'),
    tag: document.getElementById('filter-tag'),
    yearMin: document.getElementById('filter-year-min'),
    yearMax: document.getElementById('filter-year-max'),
};

// Tab handling
tabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const tabId = tab.dataset.tab;
        tabs.forEach(t => t.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`tab-${tabId}`).classList.add('active');
        if (tabId === 'browse') loadEntries();
    });
});

// Filter handling with debounce
Object.values(filterInputs).forEach(input => {
    input.addEventListener('input', () => {
        clearTimeout(filterDebounceTimer);
        filterDebounceTimer = setTimeout(() => {
            entriesPage = 0;
            loadEntries();
        }, 300);
    });
});

// Upload handling
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    handleFileSelect(Array.from(e.dataTransfer.files));
});
fileInput.addEventListener('change', e => {
    handleFileSelect(Array.from(e.target.files));
});

function handleFileSelect(files) {
    selectedFiles = files.filter(f => f.name.endsWith('.md'));
    if (selectedFiles.length === 0) {
        dropZone.querySelector('p').textContent = 'No .md files selected';
        uploadBtn.disabled = true;
        return;
    }
    dropZone.classList.add('has-file');
    dropZone.querySelector('p').textContent =
        selectedFiles.length === 1
            ? `Selected: ${selectedFiles[0].name}`
            : `Selected: ${selectedFiles.length} files`;
    uploadBtn.disabled = false;
}

uploadForm.addEventListener('submit', async e => {
    e.preventDefault();
    if (selectedFiles.length === 0) return;
    uploadBtn.disabled = true;
    uploadStatus.innerHTML = `<p class="info">Uploading ${selectedFiles.length} file(s)...</p>`;

    let success = 0;
    let failed = 0;
    for (const file of selectedFiles) {
        const formData = new FormData();
        formData.append('file', file);
        try {
            const resp = await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData });
            const data = await resp.json();
            if (resp.ok) {
                uploadStatus.innerHTML += `<p class="success">${data.title} (${data.entry_id})</p>`;
                success++;
            } else {
                uploadStatus.innerHTML += `<p class="error">${file.name}: ${data.detail || 'Error'}</p>`;
                failed++;
            }
        } catch (err) {
            uploadStatus.innerHTML += `<p class="error">${file.name}: ${err.message}</p>`;
            failed++;
        }
    }
    uploadStatus.innerHTML += `<p class="info">Done. Uploaded: ${success}, Failed: ${failed}</p>`;
    selectedFiles = [];
    dropZone.classList.remove('has-file');
    dropZone.querySelector('p').textContent = 'Drag & drop _libraryentry.md files here or click to select';
    uploadBtn.disabled = true;
    fileInput.value = '';
});

// Browse: load entries
async function loadEntries() {
    const skip = entriesPage * ENTRIES_PER_PAGE;
    const params = new URLSearchParams({ skip, limit: ENTRIES_PER_PAGE });
    if (filterInputs.title.value) params.set('title', filterInputs.title.value);
    if (filterInputs.author.value) params.set('author', filterInputs.author.value);
    if (filterInputs.genre.value) params.set('genre', filterInputs.genre.value);
    if (filterInputs.tag.value) params.set('tag', filterInputs.tag.value);
    if (filterInputs.yearMin.value) params.set('year_min', filterInputs.yearMin.value);
    if (filterInputs.yearMax.value) params.set('year_max', filterInputs.yearMax.value);

    try {
        const resp = await fetch(`${API_BASE}/entries?${params}`);
        const data = await resp.json();
        entriesTotal = data.total;
        renderEntries(data.entries);
        renderEntriesPagination();
        entriesCount.textContent = `${data.total} entries found`;
    } catch (err) {
        entriesList.innerHTML = `<p class="error">Failed to load: ${err.message}</p>`;
    }
}

function renderEntries(entries) {
    if (entries.length === 0) {
        entriesList.innerHTML = '<p class="loading">No entries found.</p>';
        return;
    }
    entries.forEach(e => { entriesMap[e.id] = e; });
    entriesList.innerHTML = entries.map(e => `
        <div class="entry-item">
            <div class="entry-info-col">
                <div class="entry-title">${esc(e.title)}</div>
                <div class="entry-meta">${esc(e.author)}${e.publication_year ? ` (${e.publication_year})` : ''}${e.genre ? ` · ${esc(e.genre)}` : ''}</div>
                <div class="entry-pages">Pages: ss=${e.shortsummary_pages} | sum=${e.summary_pages} | full=${e.fulltext_pages}</div>
                ${e.custom_tags.length ? `<div class="entry-tags">${e.custom_tags.map(t => `<span class="tag-badge">${esc(t)}</span>`).join('')}</div>` : ''}
            </div>
            <div class="entry-actions">
                <button class="read-btn" onclick="openEntry('${e.id}')">Read</button>
            </div>
        </div>
    `).join('');
}

function renderEntriesPagination() {
    const totalPages = Math.ceil(entriesTotal / ENTRIES_PER_PAGE);
    if (totalPages <= 1) { entriesPagination.innerHTML = ''; return; }
    entriesPagination.innerHTML = `
        <button ${entriesPage === 0 ? 'disabled' : ''} onclick="goEntriesPage(${entriesPage - 1})">Prev</button>
        <span class="page-info">${entriesPage + 1} / ${totalPages}</span>
        <button ${entriesPage >= totalPages - 1 ? 'disabled' : ''} onclick="goEntriesPage(${entriesPage + 1})">Next</button>
    `;
}

function goEntriesPage(page) {
    entriesPage = page;
    loadEntries();
}

// Read: open entry
function openEntry(id) {
    const meta = entriesMap[id];
    currentEntryId = id;
    currentEntryMeta = meta;
    currentSection = 'shortsummary';
    currentPage = 1;

    // Switch to read tab
    tabs.forEach(t => t.classList.remove('active'));
    tabContents.forEach(c => c.classList.remove('active'));
    document.querySelector('[data-tab="read"]').classList.add('active');
    document.getElementById('tab-read').classList.add('active');

    window.scrollTo(0, 0);
    readPlaceholder.style.display = 'none';
    readContent.style.display = 'block';
    readEntryInfo.innerHTML = `
        <h2>${esc(meta.title)}</h2>
        <div class="meta">${esc(meta.author)}${meta.publication_year ? ` (${meta.publication_year})` : ''}${meta.genre ? ` · ${esc(meta.genre)}` : ''}</div>
    `;

    sectionBtns.forEach(b => b.classList.toggle('active', b.dataset.section === 'shortsummary'));
    loadPage();
}

// Section switching
sectionBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        currentSection = btn.dataset.section;
        currentPage = 1;
        sectionBtns.forEach(b => b.classList.toggle('active', b === btn));
        loadPage();
    });
});

// Load page content
async function loadPage() {
    if (!currentEntryId) return;
    pageContentEl.textContent = 'Loading...';
    pagePagination.innerHTML = '';

    try {
        const params = new URLSearchParams({ section: currentSection, page: currentPage });
        const resp = await fetch(`${API_BASE}/entries/${currentEntryId}/page?${params}`);
        const data = await resp.json();
        if (!resp.ok) {
            pageContentEl.textContent = data.detail || 'Error loading page';
            return;
        }
        currentTotalPages = data.total_pages;
        pageContentEl.textContent = data.content || '(empty)';
        renderPagePagination();
    } catch (err) {
        pageContentEl.textContent = `Error: ${err.message}`;
    }
}

function renderPagePagination() {
    if (currentTotalPages <= 1) { pagePagination.innerHTML = ''; return; }
    pagePagination.innerHTML = `
        <button ${currentPage <= 1 ? 'disabled' : ''} onclick="goPage(${currentPage - 1})">Prev</button>
        <span class="page-info">${currentPage} / ${currentTotalPages}</span>
        <button ${currentPage >= currentTotalPages ? 'disabled' : ''} onclick="goPage(${currentPage + 1})">Next</button>
    `;
}

function goPage(page) {
    currentPage = page;
    loadPage();
}

// Search
const searchInput = document.getElementById('search-input');
const searchBtn = document.getElementById('search-btn');
const searchCount = document.getElementById('search-count');
const searchResults = document.getElementById('search-results');

searchBtn.addEventListener('click', () => doSearch());
searchInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') doSearch();
});

// Search mode toggle
const modeBtns = document.querySelectorAll('.mode-btn');
modeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        searchMode = btn.dataset.mode;
        modeBtns.forEach(b => b.classList.toggle('active', b === btn));
        searchInput.placeholder = searchMode === 'semantic'
            ? 'Describe what you\'re looking for...'
            : 'Search across all books...';
    });
});

async function doSearch() {
    const q = searchInput.value.trim();
    if (!q) return;
    searchResults.innerHTML = '<p class="loading">Searching...</p>';
    searchCount.textContent = '';

    try {
        if (searchMode === 'semantic') {
            const resp = await fetch(`${API_BASE}/semantic-search`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: q, limit: 20 }),
            });
            const data = await resp.json();
            if (!resp.ok) {
                searchResults.innerHTML = `<p class="error">${data.detail || 'Search error'}</p>`;
                return;
            }
            searchCount.textContent = `${data.total_results} semantic results`;
            renderSemanticResults(data.results);
        } else {
            const params = new URLSearchParams({ q, limit: 50 });
            const resp = await fetch(`${API_BASE}/search?${params}`);
            const data = await resp.json();
            if (!resp.ok) {
                searchResults.innerHTML = `<p class="error">${data.detail || 'Search error'}</p>`;
                return;
            }
            searchCount.textContent = `${data.total_results} results`;
            renderSearchResults(data.results);
        }
    } catch (err) {
        searchResults.innerHTML = `<p class="error">Search failed: ${err.message}</p>`;
    }
}

function renderSearchResults(results) {
    if (results.length === 0) {
        searchResults.innerHTML = '<p class="loading">No results found.</p>';
        return;
    }
    searchResults.innerHTML = results.map(r => {
        const snippet = esc(r.snippet).replace(/&gt;&gt;&gt;/g, '<span class="hl">').replace(/&lt;&lt;&lt;/g, '</span>');
        return `
            <div class="search-result-item" onclick="openSearchResult('${esc(r.entry_id)}', '${esc(r.section)}', ${r.page})">
                <div class="search-result-title">${esc(r.title)}</div>
                <div class="search-result-location">${r.section} · page ${r.page}</div>
                <div class="search-result-snippet">${snippet}</div>
            </div>
        `;
    }).join('');
}

function renderSemanticResults(results) {
    if (results.length === 0) {
        searchResults.innerHTML = '<p class="loading">No results found.</p>';
        return;
    }
    searchResults.innerHTML = results.map(r => `
        <div class="search-result-item" onclick="openSearchResult('${esc(r.entry_id)}', '${esc(r.section)}', ${r.page_number})">
            <div class="search-result-title">${esc(r.title)}</div>
            <div class="search-result-location">${esc(r.author)} · ${r.section} · page ${r.page_number}</div>
            <div class="search-result-snippet">${esc(r.snippet)}</div>
        </div>
    `).join('');
}

function openSearchResult(entryId, section, page) {
    // We need metadata for the entry. Fetch it first if not cached.
    if (entriesMap[entryId]) {
        openEntryAt(entryId, entriesMap[entryId], section, page);
    } else {
        // Fetch metadata via list_entries with a targeted approach
        fetch(`${API_BASE}/entries?limit=1&title=`)
            .then(() => {
                // Just open with minimal info
                openEntryAt(entryId, null, section, page);
            });
    }
}

function openEntryAt(id, meta, section, page) {
    currentEntryId = id;
    currentEntryMeta = meta;
    currentSection = section;
    currentPage = page;

    // Switch to read tab
    tabs.forEach(t => t.classList.remove('active'));
    tabContents.forEach(c => c.classList.remove('active'));
    document.querySelector('[data-tab="read"]').classList.add('active');
    document.getElementById('tab-read').classList.add('active');

    window.scrollTo(0, 0);
    readPlaceholder.style.display = 'none';
    readContent.style.display = 'block';

    if (meta) {
        readEntryInfo.innerHTML = `
            <h2>${esc(meta.title)}</h2>
            <div class="meta">${esc(meta.author)}${meta.publication_year ? ` (${meta.publication_year})` : ''}${meta.genre ? ` · ${esc(meta.genre)}` : ''}</div>
        `;
    } else {
        readEntryInfo.innerHTML = `<h2>Entry ${id}</h2>`;
    }

    sectionBtns.forEach(b => b.classList.toggle('active', b.dataset.section === section));
    loadPage();
}

// Utility
function esc(str) {
    const el = document.createElement('span');
    el.textContent = str || '';
    return el.innerHTML;
}

// Initial load
loadEntries();
