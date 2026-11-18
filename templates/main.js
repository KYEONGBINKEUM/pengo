/* Reusable interactions. No production URLs or server actions are inferred. */
document.addEventListener('DOMContentLoaded', function () {
    const toggle = document.querySelector('.menu-toggle');
    const nav = document.getElementById('site-nav');
    if (toggle && nav) {
        toggle.addEventListener('click', function () {
            const open = toggle.getAttribute('aria-expanded') !== 'true';
            toggle.setAttribute('aria-expanded', String(open));
            nav.classList.toggle('is-open', open);
        });
        nav.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', function () {
                nav.classList.remove('is-open');
                toggle.setAttribute('aria-expanded', 'false');
            });
        });
    }
    document.querySelectorAll('.courses').forEach(function (section) {
        const buttons = section.querySelectorAll('[data-filter]');
        buttons.forEach(function (button) {
            button.addEventListener('click', function () {
                buttons.forEach(b => b.setAttribute('aria-pressed', String(b === button)));
                section.querySelectorAll('[data-category]').forEach(function (card) {
                    card.hidden = button.dataset.filter !== '전체' && card.dataset.category !== button.dataset.filter;
                });
                section.querySelector('.course-list').scrollLeft = 0;
            });
        });
    });
    document.querySelectorAll('.go-top').forEach(b => b.addEventListener('click', () => window.scrollTo({top:0})));
});
