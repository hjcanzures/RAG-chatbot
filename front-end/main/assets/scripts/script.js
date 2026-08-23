document.addEventListener('DOMContentLoaded', () => {
    const mobileToggle = document.getElementById('mobile-toggle');
    const navLinks = document.getElementById('nav-links');

    // 1. Toggle Menu when clicking the Hamburger button
    if (mobileToggle && navLinks) {
        mobileToggle.addEventListener('click', (e) => {
            e.stopPropagation(); // Prevents the 'click outside' logic from firing immediately
            navLinks.classList.toggle('active');
        });
    }

    // 2. NEW: Hide menu when touching anywhere else on the document
    document.addEventListener('click', (e) => {
        // If the menu is open AND the click was NOT on the menu or the toggle button
        if (navLinks.classList.contains('active') && 
            !navLinks.contains(e.target) && 
            !mobileToggle.contains(e.target)) {
            navLinks.classList.remove('active');
        }
    });

    // 3. Handle Mega Menu Dropdowns on Mobile
    const dropdownToggles = document.querySelectorAll('.dropdown-toggle');
    dropdownToggles.forEach(toggle => {
        toggle.addEventListener('click', function(e) {
            if (window.innerWidth <= 768) {
                e.preventDefault(); 
                e.stopPropagation(); // Prevents closing the whole menu when clicking a sub-link
                const parentLi = this.parentElement;
                parentLi.classList.toggle('mobile-dropdown-active');
            }
        });
    });
});
        // --- Modal Logic ---
        const modal = document.getElementById('dpoModal');
        const trigger = document.getElementById('dpoTrigger');
        const closeBtn = modal.querySelector('.btn-close');
        
        // Open modal when the footer image is clicked
        trigger.addEventListener('click', () => {
            modal.classList.add('show');
        });
        
        // Close modal when the "X" is clicked
        closeBtn.addEventListener('click', () => {
            modal.classList.remove('show');
        });
        
        // Close modal when clicking outside the modal box
        window.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('show');
            }
        });