/** Courses the recipe box is arranged by, in menu order (the add-on's recipe_text.COURSES). */
export const COURSES: { key: string; name: string }[] = [
  { key: "breakfast", name: "Breakfast & brunch" },
  { key: "starter", name: "Starters" },
  { key: "light", name: "Light bites" },
  { key: "main", name: "Main meals" },
  { key: "side", name: "Sides" },
  { key: "dessert", name: "Desserts" },
  { key: "baking", name: "Baking" },
  { key: "snack", name: "Snacks" },
  { key: "drink", name: "Drinks" },
  { key: "extra", name: "Sauces & extras" },
];

export const courseName = (key: string | null | undefined) => COURSES.find((c) => c.key === key)?.name ?? null;

/** "From Simple, page 212" */
export const bookLine = (book: string, page: number | null) => (book ? `From ${book}${page ? `, page ${page}` : ""}` : "");
