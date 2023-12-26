const { keyBindo } = require('@wavedrom/doppler');

const controlMap = {
    'zoom-in': 'zoomIn',
    'zoom-out': 'zoomOut',
    'zoom-reset': 'Alt+0',
    'jump-beginning': 'Alt+[',
    'jump-end': 'Alt+]',
    'shift-left': 'Alt+,',
    'shift-right': 'Alt+.',
}

const getControl = (pstate, els, render, cm) => {
    Object.keys(controlMap).forEach((key, value) => {
        document.getElementById(key).addEventListener('click', () => {
            if (executeControlHandler(controlMap[key], keyBindo, pstate, els, cm))
                render();
        });
    })
}

const executeControlHandler = (key, keyBindo, pstate, els, cm) => {
    if (key === 'zoomIn' || key ==='zoomOut') {
        pstate.xCursor = pstate.xTime;
        return keyBindo[key].fn(pstate, cm);
    }
    else
        return (keyBindo[key] || keyBindo.nop).fn(pstate, cm);
};
module.exports = getControl;