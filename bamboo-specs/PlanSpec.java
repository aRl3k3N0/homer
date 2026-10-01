// bamboo-specs/src/main/java/com/example/homer/PlanSpec.java
package com.example.homer;

import com.atlassian.bamboo.specs.api.BambooSpec;
import com.atlassian.bamboo.specs.api.builders.plan.Job;
import com.atlassian.bamboo.specs.api.builders.plan.Plan;
import com.atlassian.bamboo.specs.api.builders.plan.Stage;
import com.atlassian.bamboo.specs.api.builders.plan.artifact.Artifact;
import com.atlassian.bamboo.specs.api.builders.project.Project;
import com.atlassian.bamboo.specs.api.builders.task.task.ScriptTask;
import com.atlassian.bamboo.specs.api.builders.trigger.RepositoryPollingTrigger;
import com.atlassian.bamboo.specs.util.BambooSpecSerializer;

@BambooSpec
public class PlanSpec {

    public Plan plan() {
        return new Plan(
            new Project().key("HOMER").name("Homer"),
            "HOMER-CI", "Homer CI")
            .stages(
                new Stage("Lint").jobs(job("lint", "./scripts/lint.sh")),
                new Stage("Typecheck").jobs(job("typecheck", "./scripts/typecheck.sh")),
                new Stage("Test").jobs(
                    job("test-py311", "./scripts/test.sh && COVERAGE=1 ./scripts/test.sh"),
                    job("test-py39",  "PYTHON=python3.9 ./scripts/test.sh"),
                    job("test-py310", "PYTHON=python3.10 ./scripts/test.sh"),
                    job("test-py312", "PYTHON=python3.12 ./scripts/test.sh")
                ),
                new Stage("Docs").jobs(job("docs", "./scripts/docs.sh")),
                new Stage("Package").jobs(job("package", "./scripts/package.sh")),
                new Stage("Docker").jobs(job("docker-build", "PUSH=1 LOGIN=1 ./scripts/docker.sh")),
                new Stage("Release").jobs(job("release",
                    "GH_TOKEN=$bamboo_github_token ./scripts/release.sh"))
            )
            .triggers(new RepositoryPollingTrigger());
    }

    private Job job(String name, String script) {
        return new Job(name, name)
            .tasks(
                new ScriptTask()
                    .interpreter(ScriptTask.Interpreter.SHELL)
                    .inlineBody("set -e\nchmod +x scripts/*.sh\n" + script)
            );
    }

    public static void main(String[] args) {
        BambooSpecSerializer.save(BambooSpecSerializer.serialize(new PlanSpec().plan()));
    }
}
