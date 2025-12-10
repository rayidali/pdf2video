// DOM Elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileInfo = document.getElementById('file-info');
const fileName = document.getElementById('file-name');
const removeFileBtn = document.getElementById('remove-file');
const uploadBtn = document.getElementById('upload-btn');
const uploadSection = document.getElementById('upload-section');
const processingSection = document.getElementById('processing-section');
const resultsSection = document.getElementById('results-section');
const jobIdEl = document.getElementById('job-id');
const jobStatusEl = document.getElementById('job-status');
const processBtn = document.getElementById('process-btn');
const processingSpinner = document.getElementById('processing-spinner');
const markdownPreview = document.getElementById('markdown-preview');
const markdownRaw = document.getElementById('markdown-raw');
const copyBtn = document.getElementById('copy-btn');
const newUploadBtn = document.getElementById('new-upload-btn');
const tabBtns = document.querySelectorAll('.tab-btn');
const planBtn = document.getElementById('plan-btn');
const planSection = document.getElementById('plan-section');
const planSpinner = document.getElementById('plan-spinner');
const planContent = document.getElementById('plan-content');
const planTitle = document.getElementById('plan-title');
const planSummary = document.getElementById('plan-summary');
const planDuration = document.getElementById('plan-duration');
const planSlidesCount = document.getElementById('plan-slides-count');
const slidesContainer = document.getElementById('slides-container');
const planJson = document.getElementById('plan-json');
const copyPlanBtn = document.getElementById('copy-plan-btn');
const newUploadBtnResults = document.getElementById('new-upload-btn-results');
const manimBtn = document.getElementById('manim-btn');
const manimSection = document.getElementById('manim-section');
const manimSpinner = document.getElementById('manim-spinner');
const manimContent = document.getElementById('manim-content');
const manimSlidesCount = document.getElementById('manim-slides-count');
const manimSlidesContainer = document.getElementById('manim-slides-container');

// State
let selectedFile = null;
let currentJobId = null;

// File Selection
dropZone.addEventListener('click', (e) => {
    // Only trigger if clicking the drop zone itself, not the label/button inside
    if (e.target === dropZone || e.target.closest('.drop-zone-content') && !e.target.closest('label')) {
        fileInput.click();
    }
});

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');

    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0].type === 'application/pdf') {
        handleFileSelect(files[0]);
    } else {
        showToast('Please select a PDF file', 'error');
    }
});

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFileSelect(e.target.files[0]);
    }
});

function handleFileSelect(file) {
    selectedFile = file;
    fileName.textContent = file.name;
    dropZone.classList.add('hidden');
    fileInfo.classList.remove('hidden');
    uploadBtn.disabled = false;
}

removeFileBtn.addEventListener('click', () => {
    selectedFile = null;
    fileInput.value = '';
    dropZone.classList.remove('hidden');
    fileInfo.classList.add('hidden');
    uploadBtn.disabled = true;
});

// Upload
uploadBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Uploading...';

    try {
        const formData = new FormData();
        formData.append('file', selectedFile);

        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload failed');
        }

        const data = await response.json();
        currentJobId = data.job_id;

        // Show processing section
        jobIdEl.textContent = currentJobId;
        updateStatus('uploaded');
        uploadSection.classList.add('hidden');
        processingSection.classList.remove('hidden');

        showToast('PDF uploaded successfully!', 'success');
    } catch (error) {
        showToast(error.message, 'error');
        uploadBtn.disabled = false;
        uploadBtn.textContent = 'Upload PDF';
    }
});

// Process OCR
processBtn.addEventListener('click', async () => {
    if (!currentJobId) return;

    processBtn.classList.add('hidden');
    processingSpinner.classList.remove('hidden');
    updateStatus('processing');

    try {
        const response = await fetch(`/api/process/${currentJobId}`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Processing failed');
        }

        const data = await response.json();

        // Fetch full markdown
        const mdResponse = await fetch(`/api/markdown/${currentJobId}`);
        const mdData = await mdResponse.json();

        // Display results
        displayMarkdown(mdData.markdown);
        updateStatus('complete');

        processingSection.classList.add('hidden');
        resultsSection.classList.remove('hidden');

        showToast('OCR completed successfully!', 'success');
    } catch (error) {
        showToast(error.message, 'error');
        updateStatus('failed');
        processBtn.classList.remove('hidden');
        processingSpinner.classList.add('hidden');
    }
});

// Display Markdown
function displayMarkdown(markdown) {
    markdownRaw.textContent = markdown;
    // Simple markdown to HTML conversion
    markdownPreview.innerHTML = simpleMarkdownToHtml(markdown);
}

function simpleMarkdownToHtml(md) {
    let html = md
        // Escape HTML
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        // Headers
        .replace(/^### (.*$)/gm, '<h3>$1</h3>')
        .replace(/^## (.*$)/gm, '<h2>$1</h2>')
        .replace(/^# (.*$)/gm, '<h1>$1</h1>')
        // Bold and Italic
        .replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        // Code blocks
        .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
        // Inline code
        .replace(/`(.*?)`/g, '<code>$1</code>')
        // Blockquotes
        .replace(/^> (.*$)/gm, '<blockquote>$1</blockquote>')
        // Unordered lists
        .replace(/^\s*[-*] (.*$)/gm, '<li>$1</li>')
        // Paragraphs
        .replace(/\n\n/g, '</p><p>')
        // Line breaks
        .replace(/\n/g, '<br>');

    // Wrap in paragraph
    html = '<p>' + html + '</p>';

    // Clean up empty paragraphs
    html = html.replace(/<p><\/p>/g, '');
    html = html.replace(/<p>(<h[123]>)/g, '$1');
    html = html.replace(/(<\/h[123]>)<\/p>/g, '$1');
    html = html.replace(/<p>(<pre>)/g, '$1');
    html = html.replace(/(<\/pre>)<\/p>/g, '$1');
    html = html.replace(/<p>(<blockquote>)/g, '$1');
    html = html.replace(/(<\/blockquote>)<\/p>/g, '$1');

    // Wrap consecutive li elements in ul
    html = html.replace(/(<li>.*?<\/li>)+/gs, '<ul>$&</ul>');

    return html;
}

// Tabs
tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;

        tabBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
            content.classList.add('hidden');
        });

        const activeTab = document.getElementById(`${tab}-tab`);
        activeTab.classList.remove('hidden');
        activeTab.classList.add('active');
    });
});

// Copy Markdown
copyBtn.addEventListener('click', async () => {
    try {
        await navigator.clipboard.writeText(markdownRaw.textContent);
        showToast('Markdown copied to clipboard!', 'success');
    } catch (error) {
        showToast('Failed to copy', 'error');
    }
});

// Generate Plan
planBtn.addEventListener('click', async () => {
    if (!currentJobId) {
        console.error('No job ID found');
        return;
    }

    console.log('=== Starting Plan Generation ===');
    console.log('Job ID:', currentJobId);

    planBtn.disabled = true;
    planBtn.textContent = 'Generating...';

    // Show plan section with spinner
    planSection.classList.remove('hidden');
    planSpinner.classList.remove('hidden');
    planContent.classList.add('hidden');

    // Scroll to plan section so user can see the spinner
    planSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    console.log('Calling API: POST /api/plan/' + currentJobId);

    try {
        const response = await fetch(`/api/plan/${currentJobId}`, {
            method: 'POST'
        });

        console.log('Response status:', response.status);

        if (!response.ok) {
            const error = await response.json();
            console.error('API Error:', error);
            throw new Error(error.detail || 'Planning failed');
        }

        const data = await response.json();
        console.log('Plan received:', data);
        console.log('Number of slides:', data.plan?.slides?.length);

        displayPlan(data.plan);

        planSpinner.classList.add('hidden');
        planContent.classList.remove('hidden');
        resultsSection.classList.add('hidden');

        showToast('Plan generated successfully!', 'success');
        console.log('=== Plan Generation Complete ===');
    } catch (error) {
        console.error('Planning failed:', error);
        showToast(error.message, 'error');
        planSpinner.classList.add('hidden');
        planSection.classList.add('hidden');
        planBtn.disabled = false;
        planBtn.textContent = 'Generate Plan';
    }
});

// Display Plan
function displayPlan(plan) {
    planTitle.textContent = plan.paper_title;
    planSummary.textContent = plan.paper_summary;
    planDuration.textContent = plan.target_duration_minutes;
    planSlidesCount.textContent = plan.slides.length;
    planJson.textContent = JSON.stringify(plan, null, 2);

    slidesContainer.innerHTML = '';
    plan.slides.forEach((slide, index) => {
        const slideEl = document.createElement('div');
        slideEl.className = 'slide-card';
        slideEl.innerHTML = `
            <div class="slide-header">
                <span class="slide-num">${slide.slide_number}</span>
                <h4>${slide.title}</h4>
                <span class="slide-type">${slide.visual_type}</span>
            </div>
            <div class="slide-body">
                <p class="slide-visual"><strong>Visual:</strong> ${slide.visual_description}</p>
                <div class="slide-points">
                    <strong>Key Points:</strong>
                    <ul>${slide.key_points.map(p => `<li>${p}</li>`).join('')}</ul>
                </div>
                <p class="slide-script"><strong>Narration:</strong> ${slide.voiceover_script}</p>
                <p class="slide-duration">${slide.duration_seconds}s</p>
            </div>
        `;
        slidesContainer.appendChild(slideEl);
    });
}

// Copy Plan JSON
copyPlanBtn.addEventListener('click', async () => {
    try {
        await navigator.clipboard.writeText(planJson.textContent);
        showToast('Plan JSON copied to clipboard!', 'success');
    } catch (error) {
        showToast('Failed to copy', 'error');
    }
});

// Generate Manim Code
manimBtn.addEventListener('click', async () => {
    if (!currentJobId) {
        console.error('No job ID found');
        return;
    }

    console.log('=== Starting Manim Code Generation ===');
    console.log('Job ID:', currentJobId);

    manimBtn.disabled = true;
    manimBtn.textContent = 'Generating...';

    // Show manim section with spinner
    manimSection.classList.remove('hidden');
    manimSpinner.classList.remove('hidden');
    manimContent.classList.add('hidden');

    // Scroll to manim section so user can see the spinner
    manimSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    console.log('Calling API: POST /api/manim/' + currentJobId);

    try {
        const response = await fetch(`/api/manim/${currentJobId}`, {
            method: 'POST'
        });

        console.log('Response status:', response.status);

        if (!response.ok) {
            const error = await response.json();
            console.error('API Error:', error);
            throw new Error(error.detail || 'Manim generation failed');
        }

        const data = await response.json();
        console.log('Manim code received:', data);
        console.log('Number of slides generated:', data.slides_generated);

        // Fetch full code for each slide
        const fullDataResponse = await fetch(`/api/manim/${currentJobId}`);
        const fullData = await fullDataResponse.json();

        displayManimCode(fullData.slides);

        manimSpinner.classList.add('hidden');
        manimContent.classList.remove('hidden');
        planSection.classList.add('hidden');

        showToast('Manim code generated successfully!', 'success');
        console.log('=== Manim Code Generation Complete ===');
    } catch (error) {
        console.error('Manim generation failed:', error);
        showToast(error.message, 'error');
        manimSpinner.classList.add('hidden');
        manimSection.classList.add('hidden');
        manimBtn.disabled = false;
        manimBtn.textContent = 'Generate Manim Code';
    }
});

// Display Manim Code
function displayManimCode(slides) {
    manimSlidesCount.textContent = slides.length;

    manimSlidesContainer.innerHTML = '';
    slides.forEach((slide) => {
        const slideEl = document.createElement('div');
        slideEl.className = 'slide-card manim-slide';
        slideEl.innerHTML = `
            <div class="slide-header">
                <span class="slide-num">${slide.slide_id}</span>
                <h4>${slide.title}</h4>
                <span class="slide-type">${slide.class_name}</span>
            </div>
            <div class="slide-body">
                <div class="code-container">
                    <div class="code-header">
                        <span>${slide.slide_id}.py</span>
                        <button class="btn-copy-code" data-code="${encodeURIComponent(slide.code)}">Copy</button>
                    </div>
                    <pre class="code-block"><code>${escapeHtml(slide.code)}</code></pre>
                </div>
                <p class="slide-duration">Expected: ${slide.expected_duration}s</p>
            </div>
        `;
        manimSlidesContainer.appendChild(slideEl);
    });

    // Add copy handlers for code blocks
    document.querySelectorAll('.btn-copy-code').forEach(btn => {
        btn.addEventListener('click', async () => {
            const code = decodeURIComponent(btn.dataset.code);
            try {
                await navigator.clipboard.writeText(code);
                showToast('Code copied to clipboard!', 'success');
            } catch (error) {
                showToast('Failed to copy', 'error');
            }
        });
    });
}

// Escape HTML for code display
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// New Upload - shared reset function
function resetToUpload() {
    // Reset state
    selectedFile = null;
    currentJobId = null;
    fileInput.value = '';

    // Reset UI
    dropZone.classList.remove('hidden');
    fileInfo.classList.add('hidden');
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Upload PDF';
    processBtn.classList.remove('hidden');
    processingSpinner.classList.add('hidden');
    planBtn.disabled = false;
    planBtn.textContent = 'Generate Plan';
    manimBtn.disabled = false;
    manimBtn.textContent = 'Generate Manim Code';

    // Show upload section
    resultsSection.classList.add('hidden');
    processingSection.classList.add('hidden');
    planSection.classList.add('hidden');
    manimSection.classList.add('hidden');
    uploadSection.classList.remove('hidden');
}

// New Upload button in plan section
newUploadBtn.addEventListener('click', resetToUpload);

// New Upload button in results section
newUploadBtnResults.addEventListener('click', resetToUpload);

// Status Update
function updateStatus(status) {
    jobStatusEl.textContent = status.charAt(0).toUpperCase() + status.slice(1);
    jobStatusEl.className = 'status-badge ' + status;
}

// Toast Notification
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    // Error toasts stay longer (8 seconds) so user can read them
    const duration = type === 'error' ? 8000 : 3000;

    setTimeout(() => {
        toast.remove();
    }, duration);
}
