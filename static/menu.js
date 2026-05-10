// static/menu.js
// CafeSync menu data. Edit this file to add/remove categories or items.
//
// Each category has:
//   - id:    short slug used as the tab id (no spaces, lowercase)
//   - label: shown on the tab
//   - icon:  Bootstrap Icons class (https://icons.getbootstrap.com/)
//   - items: array of { name, description, icon? }
//
// Items show up as cards in the chosen category. Clicking the "Place Order"
// button POSTs to /orders/ with { item_name: <name>, quantity: 1 }.
window.CAFESYNC_MENU = [
    {
        id: "coffee",
        label: "Coffee",
        icon: "bi-cup-hot-fill",
        items: [
            { name: "Espresso",        description: "A bold, single shot of pure espresso.", icon: "bi-cup-hot" },
            { name: "Americano",       description: "Espresso topped with hot water.",       icon: "bi-cup-straw" },
            { name: "Latte",           description: "Espresso with steamed milk and a light layer of foam.", icon: "bi-cup" },
            { name: "Cappuccino",      description: "Equal parts espresso, steamed milk, and foam.",         icon: "bi-cup-fill" },
            { name: "Mocha",           description: "Espresso with chocolate and steamed milk.",             icon: "bi-cup-hot" },
            { name: "Flat White",      description: "Espresso with velvety steamed milk.",                   icon: "bi-cup" },
        ],
    },
    {
        id: "tea",
        label: "Tea",
        icon: "bi-cup",
        items: [
            { name: "Earl Grey",     description: "Classic black tea with bergamot.",      icon: "bi-cup" },
            { name: "Green Tea",     description: "Light, refreshing Japanese sencha.",    icon: "bi-cup" },
            { name: "Chai Latte",    description: "Spiced black tea with steamed milk.",   icon: "bi-cup-fill" },
            { name: "Chamomile",     description: "Caffeine-free herbal infusion.",        icon: "bi-cup" },
        ],
    },
    {
        id: "breakfast",
        label: "Breakfast",
        icon: "bi-egg-fried",
        items: [
            { name: "Avocado Toast",   description: "Sourdough, smashed avocado, chili flakes.", icon: "bi-egg-fried" },
            { name: "Eggs Benedict",   description: "Poached eggs, hollandaise, English muffin.", icon: "bi-egg-fried" },
            { name: "Granola Bowl",    description: "House granola, yogurt, fresh berries.",      icon: "bi-egg" },
            { name: "Breakfast Wrap",  description: "Scrambled egg, cheese, bacon in a tortilla.", icon: "bi-egg-fried" },
        ],
    },
    {
        id: "pastries",
        label: "Pastries",
        icon: "bi-cake2-fill",
        items: [
            { name: "Butter Croissant",  description: "Flaky, buttery, classic.",          icon: "bi-cake2" },
            { name: "Pain au Chocolat",  description: "Croissant dough with dark chocolate.", icon: "bi-cake2-fill" },
            { name: "Blueberry Muffin",  description: "Bursting with fresh blueberries.",     icon: "bi-cake-fill" },
            { name: "Cinnamon Roll",     description: "Soft, swirled, with cream cheese frosting.", icon: "bi-cake2" },
        ],
    },
    {
        id: "cold",
        label: "Cold Drinks",
        icon: "bi-snow",
        items: [
            { name: "Iced Latte",       description: "Espresso, cold milk, over ice.",       icon: "bi-cup-straw" },
            { name: "Cold Brew",        description: "Slow-steeped, smooth, less acidic.",   icon: "bi-cup-straw" },
            { name: "Iced Matcha",      description: "Ceremonial matcha with cold milk.",    icon: "bi-cup-straw" },
            { name: "Lemonade",         description: "Fresh-squeezed, lightly sweetened.",   icon: "bi-cup-straw" },
            { name: "Sparkling Water",  description: "Chilled, with optional citrus.",       icon: "bi-droplet-half" },
        ],
    },
];
