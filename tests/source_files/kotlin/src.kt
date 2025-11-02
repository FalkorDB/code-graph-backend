// Test Kotlin file for analyzer
fun log(msg: String) {
    println(msg)
}

interface Task {
    fun execute()
}

class WorkerTask(val name: String, var duration: Int) : Task {
    override fun execute() {
        log("Executing task: $name")
    }

    fun abort(delay: Float): WorkerTask {
        log("Aborting task")
        return this
    }
}

object TaskManager {
    fun createTask(name: String): WorkerTask {
        return WorkerTask(name, 0)
    }
}

fun main() {
    val task = TaskManager.createTask("Test")
    task.execute()
}
