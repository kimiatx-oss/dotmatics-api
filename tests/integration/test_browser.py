import os
import uuid

import pytest

pytestmark = pytest.mark.integration


def test_projects(browser):
    assert isinstance(browser.projects_by_id, dict)


def test_configured_query_and_data(browser, browser_mapping):
    project, datasource, column, value = browser_mapping
    result = browser.run_query(
        column, "equals", value, project=project, datasources=[datasource], limit=10
    )
    assert isinstance(result, dict) and isinstance(result.get("ids"), list)
    if not result["ids"]:
        pytest.skip("Configured query matched no records")
    data = browser.fetch_data(
        project=project, datasources=[datasource], ids=result["ids"]
    )
    assert isinstance(data, dict)
    assert set(str(pk) for pk in result["ids"]) <= set(data)


def test_upload_validate_sdf(browser, input_dir, mutation_opt_in):
    file_id = browser.upload_sdf(str(input_dir / "aspirin.sdf"))
    assert isinstance(file_id, int)
    result = browser.validate_sdf(file_id)
    assert isinstance(result, dict) and "itemInFile" in result
    # Uploads remain in server temporary storage; no persistent registry write is made.


def test_experiment_lifecycle(browser, mutation_opt_in):
    protocol = os.environ.get("DOTMATICS_TEST_PROTOCOL_ID")
    if not protocol:
        pytest.skip("Set DOTMATICS_TEST_PROTOCOL_ID to a dedicated test protocol")
    name = "itest-" + uuid.uuid4().hex
    response = browser.create_experiment(
        int(protocol),
        browser.user,
        name=name,
        description="Synthetic integration fixture",
        automated="Y",
    )
    data = response.get("data", response)
    pk = data.get("experimentID") or data.get("id") or data.get("studyId")
    assert pk is not None, (
        "Create returned no ID; inspect this run's name before manual cleanup"
    )
    try:
        browser.update_experiment(int(pk), name=name + "-updated")
        browser.complete_experiment(
            int(pk),
            countersigner_isid=browser.user,
            comment="Synthetic integration fixture",
        )
    finally:
        browser.delete_experiment(int(pk))
