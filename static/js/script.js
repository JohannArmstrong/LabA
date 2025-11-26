// dark theme con bootstrap
document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("theme-toggle");
    const htmlTag = document.documentElement;

    // uso de local storage para guardar el tema actual
    const savedTheme = localStorage.getItem("theme");
    if (savedTheme) {
        htmlTag.setAttribute("data-bs-theme", savedTheme);
    } else {
        htmlTag.setAttribute("data-bs-theme", "dark"); // por defecto oscuro
        localStorage.setItem("theme", "dark");
    }

    // alternar tema mediante bot'on
        btn.addEventListener("click", function () {
            const currentTheme = htmlTag.getAttribute("data-bs-theme");
            const newTheme = currentTheme === "light" ? "dark" : "light";
            htmlTag.setAttribute("data-bs-theme", newTheme);
            localStorage.setItem("theme", newTheme); // guardar estado
        });
});


document.getElementById("toggle-all").addEventListener("click", function() {
  const checkboxes = document.querySelectorAll("input[name=columnas]");
  // sees if at least 1 is checkd
  const allChecked = Array.from(checkboxes).every(cb => cb.checked);
  checkboxes.forEach(cb => cb.checked = !allChecked);
});


/*not in use but still here
// hide columns (also in pdf)
document.getElementById("apply-columns").addEventListener("click", function() {
  const checkboxes = document.querySelectorAll("#column-selector input[type=checkbox]");
  const table = document.getElementById("proyectos");
  
  checkboxes.forEach(cb => {
    const colIndex = cb.getAttribute("data-col");
    const display = cb.checked ? "" : "none";
    
    // hide/show head
    table.querySelectorAll("th")[colIndex].style.display = display;
    // hide/show cells in each row
    table.querySelectorAll("tr").forEach(row => {
      const cells = row.querySelectorAll("td, th");
      if (cells[colIndex]) {
        cells[colIndex].style.display = display;
      }
    });
  });
});*/
