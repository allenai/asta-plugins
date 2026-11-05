// Self-contained so Playwright can evaluate it in the document as well as Node.
export function documentUrls(elements) {
  return elements.map(element => {
    const value = element.getAttribute("href") ?? element.getAttribute("src");
    return new URL(value, element.baseURI).href;
  });
}
