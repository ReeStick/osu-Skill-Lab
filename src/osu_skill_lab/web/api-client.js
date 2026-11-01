export async function request(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`Сервис вернул неверный ответ (${response.status})`);
  }
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(
      typeof detail === "string"
        ? detail
        : detail?.message ||
          (Array.isArray(detail)
            ? detail.map((item) => item.msg).join("; ")
            : `Сервис недоступен (${response.status})`),
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
export const api = (path, body) =>
  request(
    "/lab/api" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
