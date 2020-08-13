from .topping import Topping

class EnchantmentsTopping(Topping):
    """Provides a list of all enchantments"""

    PROVIDES = [
        "enchantments"
    ]
    DEPENDS = ["identify.enchantments"]

    @staticmethod
    def act(aggregate, classloader, verbose=False):
        enchantments = []
        cf = classloader[aggregate["classes"]["enchantments"]]
        # Method is either <clinit> or a void with no parameters, check both
        # until we find one that loads constants
        for meth in cf.methods.find(args = '', returns = 'V'):
            ops = tuple(meth.code.disassemble())
            if(next(x for x in ops if 'ldc' in x.name), False):
                break
        for idx, op in enumerate(ops):
            if 'ldc' in op.name:
                str_val = op.operands[0].string.value

                # Enum identifiers in older version of MC are all uppercase,
                # these are distinct from the enchantment strings we're
                # collecting here.
                if str_val.isupper():
                    continue

                enchantments.append(str_val)

        aggregate['enchantments'] = enchantments
