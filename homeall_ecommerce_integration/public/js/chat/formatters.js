export function title(item) {
	return item?.title || item?.customer?.full_name || item?.customer?.username || 'Customer';
}

export function appLabel(item) {
	return item?.app_key === 'dsku-wholesale' ? 'DSKU' : 'CSL';
}

export function initial(item) {
	return title(item).slice(0, 1).toUpperCase();
}

export function time(value) {
	return value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
}

export function day(value) {
	return new Date(value).toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
}

export function inboxTime(value) {
	return value ? (day(value) === day(new Date()) ? time(value) :
		new Date(value).toLocaleDateString([], { month: 'short', day: 'numeric' })) : '';
}
