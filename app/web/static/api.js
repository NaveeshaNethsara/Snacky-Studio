/** A single boundary for JSON requests and readable API errors. */
export class ApiError extends Error {
    constructor(message, status = 0) {
        super(message);
        this.status = status;
    }
}

export async function request(path, { method = 'GET', body, signal } = {}) {
    let response;
    try {
        response = await fetch(path, {
            method, signal, cache: 'no-store',
            headers: body ? { 'Content-Type': 'application/json' } : {},
            body: body ? JSON.stringify(body) : undefined,
        });
    } catch (error) {
        if (error.name === 'AbortError') throw error;
        throw new ApiError('Cannot reach Snacky Studio. Check that the local server is running.');
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = Array.isArray(data.detail)
            ? data.detail.map(item => item.msg).join(' ')
            : data.detail;
        throw new ApiError(detail || `Request failed (${response.status}). Please try again.`, response.status);
    }
    return data;
}

