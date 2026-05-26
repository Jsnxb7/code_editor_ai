/* ============================================================
   Bob IDE — ide.js  v0.2
   ============================================================ */

let editor;
let currentProject = "sample_project";
let currentFile = null;
let dirty = false;
let isRunning = false;

const $ = (id) => document.getElementById(id);

/* ── API helper ── */
function api(url, options = {}) {
  return fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  }).then(async (res) => {
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "Request failed");
    return data.data;
  });
}

/* ── Language detection ── */
function extToLang(path) {
  const ext = path.split('.').pop().toLowerCase();
  return {
    py: 'python', html: 'html', css: 'css', js: 'javascript',
    json: 'json', md: 'markdown', txt: 'plaintext',
    yaml: 'yaml', yml: 'yaml'
  }[ext] || 'plaintext';
}

function langIcon(lang) {
  return { python:'🐍', html:'🌐', css:'🎨', javascript:'⚡',
           json:'{ }', markdown:'📝', plaintext:'📄' }[lang] || '◦';
}

/* ── Dirty state ── */
function markDirty(value) {
  dirty = value;
  const el = $('saveState');
  const tab = $('activeFileTab');
  if (value) {
    el.textContent = '● Unsaved';
    el.className = 'save-state unsaved';
    tab.classList.add('unsaved');
  } else {
    el.textContent = currentFile ? '✓ Saved' : '';
    el.className = 'save-state' + (currentFile ? ' saved' : '');
    tab.classList.remove('unsaved');
  }
}

/* ── Terminal output ── */
function termLine(text, type = 'out') {
  const pre = $('terminal');
  const line = document.createElement('div');
  line.className = `term-line`;
  if (type === 'prompt') {
    line.innerHTML = `<span class="term-prompt">❯</span><span class="term-out">${escHtml(text)}</span>`;
  } else if (type === 'err') {
    line.innerHTML = `<span class="term-err">${escHtml(text)}</span>`;
  } else if (type === 'sys') {
    line.innerHTML = `<span class="term-sys">${escHtml(text)}</span>`;
  } else {
    line.innerHTML = `<span class="term-out">${escHtml(text)}</span>`;
  }
  pre.appendChild(line);
  pre.scrollTop = pre.scrollHeight;
}

function clearTerminal() {
  $('terminal').innerHTML = '';
}

function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Tab switch ── */
function switchTab(tab) {
  document.querySelectorAll('.bottom-tabs button').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.tab === tab));
  document.querySelectorAll('.bottom-content').forEach(el =>
    el.classList.toggle('active', el.id === tab));
}

/* ── Running state ── */
function setRunning(running) {
  isRunning = running;
  $('runBtn').style.display = running ? 'none' : '';
  $('stopBtn').style.display = running ? '' : 'none';
}

/* ── Tree renderer ── */
function renderTree(node, container) {
  container.innerHTML = '';
  const hint = $('treeHint');

  if (!node.children || !node.children.length) {
    hint.style.display = '';
    return;
  }
  hint.style.display = 'none';

  function makeNode(item, parent) {
    if (item.type === 'folder') {
      const wrapper = document.createElement('div');

      const row = document.createElement('div');
      row.className = 'tree-folder-row';
      row.innerHTML = `<span class="icon">▸</span><span>${escHtml(item.name)}</span>`;

      const children = document.createElement('div');
      children.className = 'tree-children';
      let open = true;

      row.onclick = () => {
        open = !open;
        children.style.display = open ? '' : 'none';
        row.querySelector('.icon').textContent = open ? '▾' : '▸';
      };

      wrapper.appendChild(row);
      if (item.children && item.children.length) {
        item.children.forEach(child => makeNode(child, children));
      }
      wrapper.appendChild(children);
      parent.appendChild(wrapper);

    } else {
      const row = document.createElement('div');
      row.className = 'tree-item file';
      row.dataset.path = item.path;

      const lang = extToLang(item.path);
      const icon = langIcon(lang);
      row.innerHTML = `<span class="icon">${icon}</span><span>${escHtml(item.name)}</span>`;
      row.onclick = () => openFile(item.path);

      if (item.path === currentFile) row.classList.add('active');
      parent.appendChild(row);
    }
  }

  node.children.forEach(child => makeNode(child, container));
}

/* ── Load workspaces ── */
async function loadWorkspaces() {
  const data = await api('/api/workspaces');
  const sel = $('workspaceSelect');
  sel.innerHTML = '';
  data.projects.forEach(p => {
    const opt = document.createElement('option');
    opt.value = opt.textContent = p;
    sel.appendChild(opt);
  });
  if (data.projects.includes(currentProject)) sel.value = currentProject;
  else if (data.projects[0]) currentProject = data.projects[0];
  $('statusProject').textContent = currentProject;
  await loadTree();
}

/* ── Load tree ── */
async function loadTree() {
  const tree = await api(`/api/project/tree?project=${encodeURIComponent(currentProject)}`);
  renderTree(tree, $('tree'));
}

/* ── Open file ── */
async function openFile(path) {
  if (dirty && !confirm('Unsaved changes — discard and open?')) return;
  const data = await api(`/api/file/read?project=${encodeURIComponent(currentProject)}&path=${encodeURIComponent(path)}`);
  currentFile = data.path;
  editor.setValue(data.content);
  monaco.editor.setModelLanguage(editor.getModel(), extToLang(path));
  editor.setScrollPosition({ scrollTop: 0 });

  // Update tab
  $('tabLabel').textContent = path;
  $('activeFileTab').classList.add('has-file');

  // Highlight in tree
  document.querySelectorAll('.tree-item.file').forEach(el =>
    el.classList.toggle('active', el.dataset.path === path));

  $('bobCurrentFile').textContent = path;
  $('statusFile').textContent = path;
  $('statusLang').textContent = extToLang(path).toUpperCase();
  markDirty(false);
}

/* ── Save ── */
async function saveFile() {
  if (!currentFile) { showToast('Open a file first', 'warn'); return; }
  await api('/api/file/save', {
    method: 'POST',
    body: JSON.stringify({ project: currentProject, path: currentFile, content: editor.getValue() })
  });
  markDirty(false);
  switchTab('terminal');
  termLine(`Saved: ${currentFile}`, 'sys');
}

/* ── Validate ── */
async function validateFile() {
  if (!currentFile) { showToast('Open a file first', 'warn'); return; }
  const data = await api('/api/validate', {
    method: 'POST',
    body: JSON.stringify({ path: currentFile, content: editor.getValue() })
  });
  const box = $('problems');
  box.innerHTML = '';

  if (!data.problems.length) {
    box.innerHTML = '<div class="problem" style="color:var(--green);border-color:rgba(82,214,138,.3);">✓ No problems found</div>';
    $('problemBadge').style.display = 'none';
  } else {
    data.problems.forEach(p => {
      const div = document.createElement('div');
      div.className = `problem ${p.severity}`;
      div.innerHTML = `
        <div>
          <span class="prob-sev">${p.severity.toUpperCase()}</span>
        </div>
        <div>
          <div class="prob-msg">${escHtml(p.message)}</div>
          <div class="prob-loc">Line ${p.line}</div>
        </div>`;
      box.appendChild(div);
    });
    $('problemBadge').textContent = data.problems.length;
    $('problemBadge').style.display = '';
  }
  switchTab('problems');
}

/* ── Run Python ── */
async function runPython() {
  if (!currentFile) { showToast('Open a Python file first', 'warn'); return; }
  if (!currentFile.endsWith('.py')) { showToast('Only .py files can be run', 'warn'); return; }
  if (dirty) await saveFile();
  setRunning(true);
  switchTab('terminal');
  clearTerminal();
  termLine(`python ${currentFile}`, 'prompt');
  try {
    const data = await api('/api/run/python', {
      method: 'POST',
      body: JSON.stringify({ project: currentProject, path: currentFile })
    });
    if (data.stdout) {
      data.stdout.split('\n').forEach(l => l && termLine(l, 'out'));
    }
    if (data.stderr) {
      data.stderr.split('\n').forEach(l => l && termLine(l, 'err'));
    }
    if (data.returncode !== null) {
      termLine(`— exit ${data.returncode}`, 'sys');
      setRunning(false);
    }
    // If returncode is null it's a server still running
  } catch (err) {
    termLine(err.message, 'err');
    setRunning(false);
  }
}

/* ── Stop Python ── */
async function stopPython() {
  if (!currentFile) return;
  try {
    const data = await api('/api/run/stop', {
      method: 'POST',
      body: JSON.stringify({ project: currentProject, path: currentFile })
    });
    termLine(data.message, 'sys');
  } catch (err) {
    termLine(err.message, 'err');
  }
  setRunning(false);
}

/* ── New workspace ── */
async function createWorkspace() {
  const name = prompt('New workspace name:');
  if (!name) return;
  await api('/api/workspace/create', { method: 'POST', body: JSON.stringify({ name }) });
  currentProject = name.trim().replaceAll(' ', '_');
  await loadWorkspaces();
}

/* ── New file ── */
async function createFile() {
  const path = prompt('File path (e.g. app.py or templates/index.html):');
  if (!path) return;
  await api('/api/file/create', { method: 'POST', body: JSON.stringify({ project: currentProject, path }) });
  await loadTree();
  await openFile(path);
}

/* ── New folder ── */
async function createFolder() {
  const path = prompt('Folder path (e.g. templates or static/css):');
  if (!path) return;
  await api('/api/folder/create', { method: 'POST', body: JSON.stringify({ project: currentProject, path }) });
  await loadTree();
}

/* ── Toast notifications ── */
function showToast(msg, type = 'info') {
  const t = document.createElement('div');
  t.style.cssText = `
    position:fixed;bottom:36px;right:16px;
    background:${type === 'warn' ? 'var(--surface-3)' : 'var(--surface-2)'};
    border:1px solid ${type === 'warn' ? 'var(--yellow)' : 'var(--border)'};
    color:${type === 'warn' ? 'var(--yellow)' : 'var(--text)'};
    padding:8px 14px;border-radius:var(--radius-lg);font-size:12px;
    font-family:var(--font-ui);font-weight:600;
    z-index:9999;animation:fadeIn .2s ease;
    box-shadow:0 4px 16px rgba(0,0,0,.4);
  `;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2800);
}

/* ============================================================
   Monaco Init
   ============================================================ */
require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.47.0/min/vs' } });
require(['vs/editor/editor.main'], () => {
  monaco.editor.defineTheme('bob-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '4a5060', fontStyle: 'italic' },
      { token: 'string', foreground: '98c379' },
      { token: 'keyword', foreground: 'f5a623', fontStyle: 'bold' },
      { token: 'number', foreground: '4dd9ec' },
    ],
    colors: {
      'editor.background':             '#0d0e11',
      'editor.foreground':             '#e8eaf0',
      'editor.lineHighlightBackground':'#13151a',
      'editorLineNumber.foreground':   '#3a3f4f',
      'editorLineNumber.activeForeground': '#f5a623',
      'editor.selectionBackground':    '#f5a62330',
      'editorCursor.foreground':       '#f5a623',
      'editorIndentGuide.background':  '#1f222b',
      'editorWhitespace.foreground':   '#2a2d38',
      'scrollbarSlider.background':    '#2a2d38',
    }
  });

  editor = monaco.editor.create($('editor'), {
    value: '# Open a file from the workspace to start editing\n',
    language: 'python',
    theme: 'bob-dark',
    automaticLayout: true,
    fontSize: 13.5,
    fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
    fontLigatures: true,
    lineHeight: 22,
    minimap: { enabled: true, scale: 1 },
    wordWrap: 'on',
    scrollBeyondLastLine: false,
    renderLineHighlight: 'gutter',
    smoothScrolling: true,
    cursorBlinking: 'phase',
    cursorSmoothCaretAnimation: 'on',
    bracketPairColorization: { enabled: true },
    padding: { top: 12, bottom: 12 },
  });

  editor.onDidChangeModelContent(() => {
    if (currentFile) markDirty(true);
  });

  // Ctrl+S to save
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, saveFile);

  termLine('Bob IDE ready — open a workspace file to begin', 'sys');
  loadWorkspaces().catch(err => termLine(`Error: ${err.message}`, 'err'));
});

/* ============================================================
   Event wiring
   ============================================================ */
$('workspaceSelect').onchange = async (e) => {
  if (dirty && !confirm('Unsaved changes — continue?')) {
    $('workspaceSelect').value = currentProject;
    return;
  }
  currentProject = e.target.value;
  currentFile = null;
  editor.setValue('# Select a file from the workspace\n');
  $('tabLabel').textContent = 'No file open';
  $('activeFileTab').classList.remove('has-file', 'unsaved');
  $('statusProject').textContent = currentProject;
  $('statusFile').textContent = 'No file';
  $('statusLang').textContent = '—';
  $('bobCurrentFile').textContent = 'None open';
  markDirty(false);
  await loadTree();
};

$('refreshBtn').onclick = () => loadWorkspaces();
$('saveBtn').onclick = saveFile;
$('validateBtn').onclick = validateFile;
$('runBtn').onclick = runPython;
$('stopBtn').onclick = stopPython;
$('newWorkspaceBtn').onclick = createWorkspace;
$('newFileBtn').onclick = createFile;
$('newFolderBtn').onclick = createFolder;

document.querySelectorAll('.bottom-tabs button').forEach(btn =>
  btn.onclick = () => switchTab(btn.dataset.tab));
