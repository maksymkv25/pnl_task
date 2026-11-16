from . import scenario


def post_init_hook(env):
    # The database's main company ("My Company") becomes Delta US Inc.
    scenario.build(env, us_company=env.ref('base.main_company'))
