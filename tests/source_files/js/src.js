function log(msg) {
    console.log(msg);
}

class Task {
    constructor(name, duration) {
        this.name = name;
        this.duration = duration;
        console.log(`name: ${name}, duration: ${duration}`);
    }

    abort(delay) {
        log(`Task ${this.name} aborted`);
        return this;
    }
}
