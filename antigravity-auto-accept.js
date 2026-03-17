/**
 * Antigravity Auto-Accept Tool
 * 
 * This script monitors the Antigravity agent chat for confirmation buttons 
 * and clicks them automatically.
 * 
 * How to use:
 * 1. Open Browser Developer Tools (F12 or Ctrl+Shift+I).
 * 2. Go to the "Console" tab.
 * 3. Paste this code and press Enter.
 */

(function () {
    console.log("%c[Antigravity Auto-Accept] Initialized. Monitoring for buttons...", "color: #4CAF50; font-weight: bold;");

    // Keywords on buttons to auto-click
    const targetKeywords = [
        "Approve",
        "Allow Always",
        "Run command",
        "Allow",
        "Confirm",
        "Yes",
        "Accept"
    ];

    function findAndClickButtons(root = document) {
        // Look for buttons
        const buttons = root.querySelectorAll('button');

        buttons.forEach(button => {
            const text = button.textContent.trim();

            // Check if button text matches any keywords (case-insensitive)
            const matches = targetKeywords.some(keyword =>
                text.toLowerCase() === keyword.toLowerCase() ||
                text.toLowerCase().includes(keyword.toLowerCase())
            );

            if (matches && !button.disabled) {
                console.log(`%c[Antigravity Auto-Accept] Clicking button: "${text}"`, "color: #2196F3;");
                button.click();
            }
        });
    }

    // Set up MutationObserver to watch for new buttons being added to the DOM
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.addedNodes.length) {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === 1) { // Element node
                        // If the added node is a button or contains a button
                        if (node.tagName === 'BUTTON') {
                            findAndClickButtons(node.parentElement);
                        } else {
                            findAndClickButtons(node);
                        }
                    }
                });
            }
        });
    });

    // Start observing
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    // Run once immediately in case buttons are already there
    findAndClickButtons();

    // Export a function to stop the observer if needed
    window.stopAntigravityAutoAccept = () => {
        observer.disconnect();
        console.log("%c[Antigravity Auto-Accept] Stopped.", "color: #f44336; font-weight: bold;");
    };
})();
